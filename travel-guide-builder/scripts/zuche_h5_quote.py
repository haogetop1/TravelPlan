# -*- coding: utf-8 -*-
"""神州租车 H5 真实报价采集（m.zuche.com/#/rent?tabCode=GNZ）。

严格遵守用户 2026-09-18 亲测的四条铁律：
  1) 入口必须是 m.zuche.com/#/rent?tabCode=GNZ
  2) 必须登录（H5 独立会话；登录态走 human_act 的 cookie 快照，跨浏览器重启复用）
  3) 必须授权定位（CDP grant_permissions + set_geolocation）
  4) 点具体车型 → 立即预订 → 租车选项确认 → **勾最低档保险** → 结算条的「全额」才是真价

安全边界（硬性）：**只读价**。绝不点「确认订单 / 提交订单 / 去支付 / 立即支付」。
本脚本只在订单确认页勾选保险，然后读结算条的数字。

关键实现细节（都是踩出来的，别改）：
  · 车型详情 / 租车选项 / 订单页这几层被 `content-visibility` 折叠 →
    文字必须用 `textContent` 取，`innerText` 会返回上一层的内容
  · 「确 认」按钮的文本中间**带空格** → 文本比较前必须去掉所有空白
  · `¥` 与数字是**不同文本节点** → 拼整页文本时不能插分隔符
  · 车型卡片的几何中心是**死区**，要点卡片里的 `img.car-img`
  · 必须用手机视口（CDP setDeviceMetricsOverride 414x896），桌面宽度下 H5 布局错位

用法：
  python zuche_h5_quote.py                     # 默认深圳 / 途观L
  python zuche_h5_quote.py --model 帕萨特       # 换车型（取列表里第一个匹配的）
  python zuche_h5_quote.py --select 尊享服务    # 指定保险档（默认自动取最低档）
"""
import argparse
import json
import os
import re
import sys
import time

# ── 找到兄弟技能 xhs-humanized-collect/scripts/（human_act / platform_compat 住那儿）──
# 逐候选目录找，命中含 human_act.py 的即用 —— 于是脚本放在技能目录里、
# 还是放在项目目录里都能跑，且**不写死任何本机绝对路径**（否则换机器/换用户名即失效，
# 还会把本机用户名泄进公开仓库）。权威候选表见 platform_compat.skills_roots()。
_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILLS_ROOT = os.path.dirname(os.path.dirname(_HERE))       # 并列安装时的 <skills_root>
_HOME = os.path.expanduser("~")
CANDS = [
    os.environ.get("XHS_SKILL_SCRIPTS", ""),
    os.environ.get("AGENT_SKILLS_DIR", ""),
    os.path.join(_SKILLS_ROOT, "xhs-humanized-collect", "scripts"),
    os.path.join(_HERE, os.pardir, os.pardir, "xhs-humanized-collect", "scripts"),
    os.path.join(_HERE, os.pardir, os.pardir, os.pardir, os.pardir,
                 ".workbuddy", "skills", "xhs-humanized-collect", "scripts"),
    os.path.join(_HOME, ".workbuddy", "skills", "xhs-humanized-collect", "scripts"),
    os.path.join(_HOME, ".claude", "skills", "xhs-humanized-collect", "scripts"),
    os.path.join(os.environ.get("LOCALAPPDATA") or _HOME,
                 "agent-skills", "skills", "xhs-humanized-collect", "scripts"),
]
for _p in CANDS:
    if _p and os.path.isfile(os.path.join(_p, "human_act.py")):
        sys.path.insert(0, os.path.abspath(_p))
        break
else:
    raise SystemExit(
        "找不到 human_act.py。\n"
        "  两个技能（travel-guide-builder / xhs-humanized-collect）必须装在**同一个**\n"
        "  skills 根目录下；或把 XHS_SKILL_SCRIPTS 指向 xhs-humanized-collect/scripts。\n"
        "已尝试：\n    %s" % "\n    ".join(x for x in CANDS if x))

from human_act import (Attached, NetLog, assert_no_captcha,  # noqa: E402
                       restore_cookies, save_cookies)

# 产物目录：优先 --out，其次环境变量 QUOTE_OUT，再次 ./prices
OUT = os.environ.get("QUOTE_OUT") or os.path.join(os.getcwd(), "prices")
ENTRY = "https://m.zuche.com/#/rent?tabCode=GNZ"
GEO = {"latitude": 22.5431, "longitude": 114.0579}      # 深圳福田
FORBID = ("确认订单", "提交订单", "去支付", "立即支付", "确认支付")
INS_NAMES = ("尊享服务", "尊享百万服务", "尊享驾乘守护", "全程无忧升级版", "全程无忧")

LOG = ""      # 在 _open_log() 里按最终 OUT 决定（--out 可能改变它）
_fh = None


def _open_log():
    global LOG, _fh
    os.makedirs(OUT, exist_ok=True)
    LOG = os.path.join(OUT, "zuche_quote.log")
    _fh = open(LOG, "w", encoding="utf-8")


def log(msg=""):
    s = str(msg)
    print(s, flush=True)
    if _fh:
        _fh.write(s + "\n")
        _fh.flush()


def norm(s):
    return re.sub(r"\s+", "", s or "")


# 整页文本：空串拼接（¥ 与数字是不同文本节点）
TEXT_JS = r"""
() => {
  const parts = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    const s = (n.nodeValue || '').trim();
    if (s) parts.push(s);
  }
  return parts.join('');
}
"""

FIND_JS = r"""
(a) => {
  const kw = (a[0] || '').replace(/\s+/g, '');
  const maxLen = a[1] || 160;
  const out = [];
  document.querySelectorAll('*').forEach(el => {
    const raw = el.textContent || '';
    const t = raw.replace(/\s+/g, '');
    if (!t || !t.includes(kw) || t.length > maxLen) return;
    const r = el.getBoundingClientRect();
    if (r.width < 20 || r.height < 14) return;
    out.push({tag: el.tagName.toLowerCase(),
              cls: (el.className || '').toString().slice(0, 40),
              text: raw.replace(/\s+/g, ' ').trim().slice(0, 60),
              w: Math.round(r.width), h: Math.round(r.height),
              left: Math.round(r.left),
              cx: Math.round(r.left + r.width/2), cy: Math.round(r.top + r.height/2),
              top: Math.round(r.top),
              leaf: ![...el.children].some(c => ((c.textContent||'').replace(/\s+/g,'') === t))});
  });
  out.sort((x, y) => x.w * x.h - y.w * y.h);
  return out.slice(0, 24);
}
"""


def mobile(page, w=414, h=896):
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setDeviceMetricsOverride",
             {"width": w, "height": h, "deviceScaleFactor": 2, "mobile": True})
    cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
    return cdp


def tap(page, x, y, settle=4000):
    page.mouse.move(max(1, x - 40), max(1, y - 25))
    page.wait_for_timeout(180)
    page.mouse.click(x, y)
    page.wait_for_timeout(settle)


def get_text(pg):
    return pg.evaluate(TEXT_JS) or ""


def wait_for(pg, kws, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        n = norm(get_text(pg))
        hit = [k for k in kws if k in n]
        if hit:
            log("   ✓ %.1fs 后出现 %s" % (time.time() - t0, hit))
            return True
        pg.wait_for_timeout(1200)
    log("   ✗ %ds 内没等到 %s" % (timeout, kws))
    return False


def find(pg, kw, max_len=160):
    return pg.evaluate(FIND_JS, [kw, max_len])


def click_kw(pg, kw, settle=5000, prefer=("button", "a", "span"), allow_forbid=False):
    cands = find(pg, kw)
    if not cands:
        log("   ✗ 找不到「%s」" % kw)
        return None
    pool = [c for c in cands if c["leaf"]] or cands
    pool.sort(key=lambda c: (0 if c["tag"] in prefer else 1, c["w"] * c["h"]))
    for c in pool:
        if not allow_forbid and any(b in norm(c["text"]) for b in FORBID):
            continue
        log("   → 点「%s」@(%d,%d) <%s class=%s>"
            % (c["text"][:26], c["cx"], c["cy"], c["tag"], c["cls"][:24]))
        tap(pg, c["cx"], c["cy"], settle=settle)
        return c
    log("   ⛔ 候选全在禁区，放弃")
    return None


def parse_order(pg):
    """从订单页文本里拆出结构化费用。

    ⚠️ 整页文本是**空串拼接**的（¥ 与数字、日期都是不同文本节点），
    所以正则要带前瞻/上下文，否则「车辆租赁及服务费￥316」会跟后面的
    「09-18 周五」粘成 ￥31609（实测踩过）。
    """
    t = get_text(pg)
    tn = norm(t)          # 去掉全部空白再匹配：日期与星期之间可能有空格
    # ¥ 被当成「数字分隔符」用：把 ￥ 换成竖线后，日期/金额的边界就清楚了。
    # 例：`￥31609-18周五￥14809-19周六￥168` → `|31609-18周五|14809-19周六|168`
    tm = tn.replace("￥", "|").replace("¥", "|")
    out = {}
    m = re.search(r"车辆租赁及服务费\|([0-9,]+?)(?=0[0-9]-[0-9]{2}周)", tm)
    if not m:
        m = re.search(r"车辆租赁及服务费\|([0-9,]+)", tm)
    out["车辆租赁及服务费"] = m.group(1) if m else ""
    # 按日租金：用 split 按「日期+星期」切段，再取每段紧跟的金额。
    # 为什么不用一个正则：`|14809-19周六|168` 里 148 后面紧接日期「09-19」，
    # 而 09 也是数字，贪婪/非贪婪都容易吃错位（实测 148 → 14809）。
    # split 后结构固定：['…|316', '09-18', '五', '|148', '09-19', '六', '|168…']
    chunks = re.split(r"(0[0-9]-[0-9]{2})周([一二三四五六日])", tm)
    per_day = []
    for i in range(1, len(chunks) - 2, 3):
        mm = re.match(r"\|([0-9,]+)", chunks[i + 2] or "")
        per_day.append({"日期": chunks[i], "星期": chunks[i + 1],
                        "价格": mm.group(1) if mm else ""})
    out["按日租金"] = per_day
    m = re.search(r"基础服务费\|([0-9]+)\*(\d+)\|([0-9,]+)", tm)
    if m:
        out["基础服务费"] = {"单价": m.group(1), "天数": m.group(2), "小计": m.group(3)}
    m = re.search(r"车辆整备费\|([0-9,]+)", tm)
    out["车辆整备费"] = m.group(1) if m else ""
    m = re.search(r"全额\|([0-9,]+)", tm)
    out["全额"] = m.group(1) if m else ""
    m = re.search(r"已选择[:：]?([^\s承我|]{2,8})", tm)
    out["已选保险"] = m.group(1) if m else ""
    out["保险已选"] = bool(out["已选保险"])
    out["未选保险提示"] = "未选择" in tn
    # 保险档位
    ins = []
    for nm in INS_NAMES:
        mm = re.search(re.escape(nm) + r"\|([0-9,]+)", tm)
        if mm:
            ins.append({"name": nm, "price": int(mm.group(1).replace(",", ""))})
    seen, uniq = set(), []
    for i in ins:
        if i["name"] not in seen:
            seen.add(i["name"])
            uniq.append(i)
    out["保险档位"] = sorted(uniq, key=lambda x: x["price"])
    return out, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("MODEL", "途观L"))
    ap.add_argument("--select", default="", help="指定保险档名（默认取最低档）")
    ap.add_argument("--no-insurance-click", action="store_true")
    ap.add_argument("--out", default="", help="产物目录（默认 QUOTE_OUT 或 ./prices）")
    args = ap.parse_args()

    global OUT
    if args.out:
        OUT = args.out
    _open_log()

    log("=== 神州租车 H5 报价采集 ===")
    log("   车型=%s | 保险=%s" % (args.model, args.select or "自动取最低档"))

    with Attached() as S:
        ctx = S.ctx
        log("   cookie 快照还原: %d 条" % restore_cookies(ctx, "zuche_h5"))
        for origin in ("https://m.zuche.com", "https://www.zuche.com"):
            try:
                ctx.grant_permissions(["geolocation"], origin=origin)
            except Exception:
                pass
        ctx.set_geolocation(GEO)

        pg = S.page
        mobile(pg)
        net = NetLog(pg, limit=1500)
        pg.goto(ENTRY, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(9000)
        assert_no_captcha(pg)

        # 登录态自检
        ui = pg.evaluate(r"""
        async () => {
          try {
            const r = await fetch('/api/gw.do?uri=/resource/carrctapi/account/getUserInfo/v1', {
              method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
              body:'data=' + encodeURIComponent(JSON.stringify({isComplated:true, isSilentMode:true}))});
            return (await r.text()).slice(0, 200);
          } catch (e) { return 'ERR ' + e; }
        }
        """)
        if "用户不存在" in ui:
            log("   ✗ H5 未登录，请先登录一次（登录态会自动存快照）")
            return 2
        log("   登录态 OK: %s" % ui[:120])

        log()
        log("① 去订车 → 车型列表")
        click_kw(pg, "去订车", settle=9000)
        wait_for(pg, ["车型详情"], timeout=15)
        list_prices = re.findall(r"[¥￥]([0-9,]+)/日均", get_text(pg))

        log()
        log("② 点车型「%s」的车图" % args.model)
        card = pg.evaluate(r"""
        (kw) => {
          const c = [...document.querySelectorAll('.vehicle-item-wrap')]
              .filter(e => (e.textContent||'').includes(kw))[0];
          if (!c) return null;
          c.scrollIntoView({block:'center', behavior:'instant'});
          const img = c.querySelector('img.car-img') || c.querySelector('img');
          const r = (img||c).getBoundingClientRect();
          return {x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2),
                  card: (c.textContent||'').replace(/\s+/g,' ').trim().slice(0,60)};
        }
        """, args.model)
        if not card:
            log("   ✗ 列表里没有含「%s」的车型" % args.model)
            return 1
        log("   卡片: %s" % card["card"])
        tap(pg, card["x"], card["y"], settle=5000)
        wait_for(pg, ["立即预订"], timeout=15)

        log()
        log("③ 立即预订 → 租车选项")
        click_kw(pg, "立即预订", settle=2000)
        wait_for(pg, ["租车选项", "取车网点"], timeout=30)
        pg.screenshot(path=OUT + "/zuche_quote_3_options.png")

        log()
        log("④ 点「确 认」（文本带空格，归一再匹）")
        click_kw(pg, "确认", settle=3000)
        wait_for(pg, ["出行保障", "价格选择", "全额"], timeout=30)
        assert_no_captcha(pg)
        pg.screenshot(path=OUT + "/zuche_quote_4_order_nobns.png")
        before, _ = parse_order(pg)
        log("   —— 未勾保险 ——")
        log("   %s" % json.dumps(before, ensure_ascii=False))

        log()
        log("⑤ 勾最低档保险")
        ins = before.get("保险档位") or []
        if not ins:
            log("   ✗ 订单页没解析到保险档位")
            return 3
        target = None
        if args.select:
            target = next((i for i in ins if args.select in i["name"]), None)
        target = target or ins[0]
        log("   档位: %s" % json.dumps(ins, ensure_ascii=False))
        log("   → 选「%s」¥%s" % (target["name"], target["price"]))

        if not args.no_insurance_click:
            # 保险表是「一格一档」的对照表：每档一列 .func-check-list，
            # 列里最后一格 .unchecked / .checked 就是「选择」行的勾选格。
            # ⚠️ 这一格往往在**折叠下方**（实测原 top=1124，视口只有 896），
            #    必须先 scrollIntoView 再重新量 rect 再点，否则点在视口外。
            got = False
            for attempt, target_cls in enumerate((".unchecked", ".price")):
                cell = pg.evaluate(r"""
                (a) => {
                  const name = a[0], pref = a[1];
                  const col = [...document.querySelectorAll('.func-check-list')]
                      .find(l => (l.textContent || '').includes(name));
                  if (!col) return null;
                  const c = col.querySelector(pref);
                  if (!c) return null;
                  c.scrollIntoView({block: 'center', behavior: 'instant'});
                  const r = c.getBoundingClientRect();
                  return {cls: (c.className||'').toString(),
                          x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2),
                          w: Math.round(r.width), h: Math.round(r.height)};
                }
                """, [target["name"], target_cls])
                if not cell:
                    log("   找不到 .%s 格" % target_cls.replace(".", ""))
                    continue
                log("   勾选格: .%s %sx%s @(%d,%d)"
                    % (cell["cls"], cell["w"], cell["h"], cell["x"], cell["y"]))
                tap(pg, cell["x"], cell["y"], settle=5000)
                assert_no_captcha(pg)
                probe, _ = parse_order(pg)
                if not probe.get("保险已选"):
                    continue
                log("   ✓ 保险已勾上（页面出现「已选择」）")
                got = True
                break
            if not got:
                log("   ✗ 保险没能勾上（金额未变化），结果里会标注")
            pg.screenshot(path=OUT + "/zuche_quote_5_insured.png")

        after, _ = parse_order(pg)
        log()
        log("⑥ 勾保险后")
        log("   %s" % json.dumps(after, ensure_ascii=False))

        summary = {
            "source": "神州租车 H5（m.zuche.com/#/rent?tabCode=GNZ）",
            "model": args.model,
            "geo": GEO,
            "未勾保险": before,
            "勾最低档保险后": after,
            "insurance_chosen": target,
            "抓取时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "说明": "订单确认页只读，未提交订单。全额 = 租金 + 基础服务费 + 整备费 + 保险",
        }
        p = os.path.join(OUT, "zuche_quote_%s.json" % re.sub(r"\W+", "", args.model))
        with open(p, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)
        log()
        log("已保存: %s" % p)
        log()
        log("=== 接口 uri ===")
        seen = []
        for r in net.items:
            if "gw.do" not in r.url:
                continue
            u = r.url.split("uri=")[-1][:78]
            if u not in seen:
                seen.append(u)
        for u in seen:
            log("   " + u)
        save_cookies(ctx, "zuche_h5")
        log()
        log("=== 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
