# -*- coding: utf-8 -*-
"""携程酒店报价采集（拟人化坐标点击 + 视觉降级）。

为什么不用「猜 URL」这一套（2026-09-17 用户对齐）
-------------------------------------------------
携程酒店的老问题是**拿不到 cityId**：城市下拉能填、但是参数化 URL 拼不出来。
真人不关心 cityId —— 人只要把城市填上、点「搜索」，列表页自己就出来了。
所以这里改成**走人走过的路**：

  ① 点目的地输入框 → 逐字输入城市（`fill()` 不触发联想，必须逐字）
  ② 点联想候选里的城市
  ③ **点右侧蓝色「搜索」按钮** ← 之前只按了 Enter，这一步从来没点过
  ④ 落地到列表页 → 三件套落盘 + 金额交叉校验

点不动的地方不猜选择器：`human_act.human_click` 会依次走
DOM 点击 → 坐标点击 → 标定坐标 → 落截图 + 候选清单交给 AI。
成功后坐标按视口比例固化到 `.workbuddy/calibration.json`，下次一次命中。

安全边界
--------
**只读价**：到列表页为止，不进下单页、不提交任何表单。
出现验证码/滑块立即中止（`CaptchaHit`）。

用法
----
  export XHS_CDP=http://127.0.0.1:9222         # 常驻会话（session_daemon.py start）
  python ctrip_hotel.py --city 深圳 --checkin 2026-10-14 --nights 3
  python ctrip_hotel.py --city 深圳 --vision ctrip:search_btn=1100,420   # 视觉给坐标后重跑
"""
import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

# human_act.py 住在兄弟技能 xhs-humanized-collect/scripts/ 下（两个技能装在同一父目录）。
# 不写绝对路径：换机器/换用户名才不会失效。可用 XHS_SKILL_SCRIPTS 覆盖。
_HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_SCRIPTS = os.environ.get("XHS_SKILL_SCRIPTS") or os.path.normpath(
    os.path.join(_HERE, "..", "..", "xhs-humanized-collect", "scripts"))
if os.path.isdir(SKILL_SCRIPTS) and SKILL_SCRIPTS not in sys.path:
    sys.path.insert(0, SKILL_SCRIPTS)

try:
    from human_act import (Attached, CaptchaHit, NeedVision, NetLog,  # noqa: E402
                           assert_no_captcha, cross_check, dump, human_click,
                           human_type, load_calib, prices_in, viewport)
except ImportError as e:
    raise SystemExit(
        "找不到 human_act.py（%s）\n  请确认 xhs-humanized-collect 技能与 travel-guide-builder "
        "装在同一目录，或设置 XHS_SKILL_SCRIPTS 指向它的 scripts/ 目录。\n  原始错误：%s"
        % (SKILL_SCRIPTS, e))

# 每个逻辑步骤的候选选择器 —— **列表顺序即优先级**。
# ⚠️ 不要用逗号拼成一个选择器：那是并集，`.first` 按 DOM 顺序取。
#    实测踩到：页头那个「搜索任何旅游相关」输入框排在酒店面板的「目的地」框之前，
#    逗号并集必然点错（2026-09-17）。
SEL = {
    # 酒店搜索面板里的目的地输入框（placeholder 恰好是「目的地」）
    "ctrip:city_input": [
        "input[placeholder='目的地']",
        "input[placeholder*='目的地']",
        "#txtCity",
        "input[name='city']",
    ],
    # 联想下拉项
    "ctrip:city_option": [
        ".cui_search_list a",
        "div[class*=cui_search_list] a",
        "div[class*=suggest] li", "div[class*=suggest] a",
        "ul[class*=suggest] li", ".city-list li",
    ],
    # 蓝色「搜索」按钮（实测中心 1257,302 / 90x48）
    "ctrip:search_btn": [
        "button:has-text('搜索')",
        "div[class*='search'] button",
        "button[class*='search']",
    ],
}


def verify_focus_placeholder(text):
    """验「焦点确实落在带某关键词的输入框上」—— 专治点错输入框。"""
    def _f(page):
        try:
            ph = page.evaluate(
                "() => (document.activeElement && (document.activeElement.placeholder || '')) || ''")
            return text in (ph or "")
        except Exception:
            return False
    return _f


def verify_left_home(text_any=("家酒店", "酒店列表", "起")):
    """验「已经从首页进到列表页」。"""
    def _f(page):
        try:
            u = page.url or ""
            if ("/list" in u) or ("city=" in u) or ("cityId" in u):
                return True
            body = page.evaluate(
                "() => (document.body ? document.body.innerText : '').slice(0, 4000)") or ""
            return any(k in body for k in text_any)
        except Exception:
            return False
    return _f


def log(msg):
    print("[ctrip] %s" % msg, flush=True)


def parse_vision(items):
    v = {}
    for it in items or []:
        k, _, xy = it.partition("=")
        try:
            x, y = xy.split(",")
            v[k.strip()] = (float(x), float(y))
        except Exception:
            raise SystemExit("--vision 格式应为 step=x,y，收到：%s" % it)
    return v


def retarget_dates(url, checkin, checkout):
    """把列表页 URL 里的日期参数换成目标日期（尽力而为，参数名不匹配就不动）。"""
    u = urlparse(url)
    q = dict(parse_qsl(u.query))
    hit = []
    for k in list(q.keys()):
        low = k.lower()
        if low in ("checkin", "check_in", "checkindate", "startdate", "begindate"):
            q[k] = checkin.replace("-", "/") if "/" in q[k] else checkin
            hit.append(k)
        elif low in ("checkout", "check_out", "checkoutdate", "enddate"):
            q[k] = checkout.replace("-", "/") if "/" in q[k] else checkout
            hit.append(k)
    if not hit:
        return None, []
    return urlunparse(u._replace(query=urlencode(q))), hit


def date_in_text(text):
    m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text or "")
    return m.group(0) if m else ""


def settle_list(page, rounds=5):
    """列表页是懒渲染：不滚一滚，innerText 里只有筛选条、没有酒店卡片。"""
    for _ in range(rounds):
        try:
            page.mouse.wheel(0, 1200)
        except Exception:
            pass
        page.wait_for_timeout(900)
    try:
        page.mouse.wheel(0, -8000)
    except Exception:
        pass
    page.wait_for_timeout(1300)


def main():
    ap = argparse.ArgumentParser(description="携程酒店报价采集（拟人化）")
    ap.add_argument("--city", default="深圳")
    ap.add_argument("--checkin", default="2026-10-14")
    ap.add_argument("--nights", type=int, default=3)
    ap.add_argument("--url", default="https://hotels.ctrip.com/")
    ap.add_argument("--out", default="")
    ap.add_argument("--cdp", default="")
    ap.add_argument("--session-dir", default="")
    ap.add_argument("--vision", action="append", default=[],
                    help="step=x,y（可多次）；来自人/AI 看截图后的判断")
    ap.add_argument("--probe", action="store_true",
                    help="只落地 + 打印可见元素候选（不点任何东西），用来定选择器")
    args = ap.parse_args()

    out = args.out or os.path.join(os.getcwd(), "prices")
    os.makedirs(out, exist_ok=True)
    vision = parse_vision(args.vision)
    if args.session_dir:
        os.environ["SCRAPE_SESSION_DIR"] = args.session_dir

    ci = time.strptime(args.checkin, "%Y-%m-%d")
    co = time.strftime("%Y-%m-%d", time.localtime(time.mktime(ci) + args.nights * 86400))
    log("城市=%s  入住=%s  离店=%s（%d 晚）  out=%s" % (args.city, args.checkin, co, args.nights, out))

    from human_act import candidates as _cands, _print_candidates
    calib = load_calib(args.session_dir or None)
    if calib:
        log("载入标定表 %d 条：%s" % (len(calib), ", ".join(sorted(calib)[:6])))

    used = []

    with Attached(cdp=args.cdp or None) as S:
        page = S.page
        net = NetLog(page)

        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3800)
        assert_no_captcha(page)
        vw, vh = viewport(page)
        log("视口 %dx%d，落地 %s" % (vw, vh, page.url))
        landing = dump(page, out, "ctrip_01_landing")

        if args.probe:
            cands = _cands(page, 80)
            log("=== probe：页面可见元素候选（全部）===")
            _print_candidates(cands, limit=60)
            band = [c for c in cands if 200 <= c.get("y", 0) <= 430]
            log("=== 搜索栏一带（y 200-430，按 x 排序）===")
            _print_candidates(sorted(band, key=lambda c: c.get("x", 0)), limit=40)
            log("probe 结束（未点击任何元素）")
            return 0

        # ① 点目的地输入框
        how, x, y, rec = human_click(
            page, "ctrip:city_input", selector=SEL["ctrip:city_input"],
            calib=calib, vision=vision, out_dir=out,
            verify=verify_focus_placeholder("目的地"),
            extra={"expect": "酒店搜索面板的目的地输入框（placeholder=目的地）"})
        used.append(("city_input", how, "%d,%d" % (x, y)))
        log("① 目的地输入框：%s (%d,%d)" % (how, x, y))

        # 逐字输入（fill() 不触发联想；中文必须走 insert_text，否则字符写两遍）
        inp = page.locator("input[placeholder='目的地']").first
        tw = human_type(page.keyboard, args.city, clear=False,
                        read_back=lambda: inp.input_value())
        log("输入回读：expected=%r actual=%r ok=%s"
            % (tw["expected"], tw["actual"], tw["ok"]))
        if not tw["ok"]:
            log("输入不一致 → 清空重输一次")
            try:
                inp.click()
                page.keyboard.press("Control+a")
                page.keyboard.press("Delete")
            except Exception:
                pass
            tw = human_type(page.keyboard, args.city, clear=False,
                            read_back=lambda: inp.input_value())
            log("重输回读：actual=%r ok=%s" % (tw["actual"], tw["ok"]))
        page.wait_for_timeout(2200)
        assert_no_captcha(page)
        drop = dump(page, out, "ctrip_02_dropdown")

        # ② 点联想候选
        try:
            how, x, y, rec = human_click(
                page, "ctrip:city_option", selector=SEL["ctrip:city_option"],
                calib=calib, vision=vision, out_dir=out,
                verify=lambda pg: args.city in (
                    pg.evaluate("() => { const i=document.querySelector(\"input[placeholder='目的地']\");"
                                " return i ? (i.value||'') : ''; }") or ""),
                extra={"expect": "城市联想下拉里的「%s」选项" % args.city})
            used.append(("city_option", how, "%d,%d" % (x, y)))
            log("② 城市候选：%s (%d,%d)" % (how, x, y))
        except NeedVision:
            log("② 城市候选取不到 → 退一步按 Enter 提交（Enter 在携程也能选中第一项）")
            page.keyboard.press("Enter")
            used.append(("city_option", "enter-fallback", ""))
        page.wait_for_timeout(2000)
        assert_no_captcha(page)
        dump(page, out, "ctrip_03_city_picked")

        # ③ 点蓝色「搜索」按钮 ← 之前漏掉的那一步
        how, x, y, rec = human_click(
            page, "ctrip:search_btn", selector=SEL["ctrip:search_btn"],
            text="搜索", calib=calib, vision=vision, out_dir=out,
            verify=verify_left_home(),
            extra={"expect": "右侧蓝色「搜索」按钮（此前只按了 Enter，从未点它）"})
        used.append(("search_btn", how, "%d,%d" % (x, y)))
        log("③ 搜索按钮：%s (%d,%d)" % (how, x, y))

        # ④ 等列表页
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(3200)
        assert_no_captcha(page)
        settle_list(page)
        lst = dump(page, out, "ctrip_04_list")
        log("④ 列表页 URL = %s" % page.url[:150])
        if args.city not in page.url and "%E6%B7%B1" not in page.url:
            log("⚠️ 结果 URL 里看不到城市 %s，可能被联想项带偏了" % args.city)

        # ⑤ 尽力把日期改成目标日期（参数名不匹配就不动）
        new_url, keys = retarget_dates(page.url, args.checkin, co)
        dated = None
        if new_url:
            log("⑤ 改写日期参数 %s → 重新导航" % keys)
            try:
                page.goto(new_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                assert_no_captcha(page)
                settle_list(page)
                dated = dump(page, out, "ctrip_05_dated")
            except CaptchaHit:
                raise
            except Exception as e:
                log("⑤ 改写后导航失败：%s" % str(e)[:100])
        else:
            log("⑤ 列表页 URL 里没有可改写的日期参数（常见于 SPA），沿用站点默认日期")

    # ---------------- 汇总 ----------------
    src = dated or lst
    dom_prices = src.get("prices", [])
    net_text = ""
    if src.get("net"):
        try:
            net_text = "\n".join(x.get("body", "") for x in
                                 json.load(open(src["net"], encoding="utf-8")))
        except Exception:
            net_text = ""
    dom_text = open(src["txt"], encoding="utf-8").read() if src.get("txt") else ""

    checked, pending = [], []
    for p in dom_prices:
        row = dict(value=p["value"], raw=p["raw"], context=p["context"],
                   verified=cross_check(p["value"], dom_text, net_text))
        (checked if row["verified"] else pending).append(row)

    summary = dict(
        platform="ctrip-hotel", city=args.city,
        checkin=args.checkin, checkout=co, nights=args.nights,
        list_url=page.url, dumps=[d.get("name") for d in (landing, drop, lst) if d],
        used_levels=used, viewport=[vw, vh],
        dom_prices_count=len(dom_prices),
        verified_prices=checked[:40], unverified_prices=pending[:40],
        net_json_count=src.get("net_count", 0),
        ts=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    sp = os.path.join(out, "ctrip_hotel_summary.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    log("=== 汇总 ===")
    log("DOM 抽到 %d 个金额；交叉校验通过 %d，待复核 %d"
        % (len(dom_prices), len(checked), len(pending)))
    for r in checked[:8]:
        log("  ✓ %-10s  %s" % (r["raw"], r["context"][:88]))
    for r in pending[:6]:
        log("  ? %-10s  %s（页面/接口里找不到同值，标待复核）" % (r["raw"], r["context"][:70]))
    log("summary → %s" % sp)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NeedVision as e:
        # 约定：退出码 3 = 需要人/AI 看图给坐标，然后带 --vision 重跑
        print("\n[ctrip] 需要视觉介入：%s" % e.step)
        print("[ctrip] 给出坐标后重跑：python ctrip_hotel.py --vision %s=<x>,<y> ..." % e.step)
        sys.exit(3)
    except CaptchaHit as e:
        print("\n[ctrip] 撞上验证码/风控，已中止（不硬试）：%s" % str(e)[:160])
        sys.exit(4)
