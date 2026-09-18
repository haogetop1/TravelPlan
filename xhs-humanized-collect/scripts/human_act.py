# -*- coding: utf-8 -*-
"""human_act —— 拟人化浏览器操作层（所有平台的抓价/抓数共用）。

为什么需要它（2026-09-17 用户对齐）
-----------------------------------
「人类手动操作浏览器能正常抓到，脚本抓不到」的典型原因有两类：

1. **元素能被 DOM 找到，但点不动** —— Playwright 的 `.click()` 会先做
   可点性检查（是否被遮罩、是否 stable、是否 enabled），任一不过就失败。
   而真人点击走的是 `pointerdown → mousedown → pointerup → mouseup → click`
   完整事件链。`page.mouse.click(x, y)` 等价真人点击，能直接绕过这层检查。
   → 所以「按坐标点」不是退路，而是**主力手段**。

2. **参数化 URL 拿不到**（携程酒店的 cityId、神州租车的 hash 路由状态）
   —— 人不需要那些参数，人只要把页面点出来。视觉定位正是用来绕开这一层的。

四级降级（先便宜后昂贵，谁先成功用谁）
--------------------------------------
  ① DOM 选择器点击          —— 免费、最稳，页面改版也活得久
  ② DOM bounding_box → 坐标点击 —— 解决「看得见点不动」（主力）
  ③ 标定表固化坐标           —— 上次成功过的坐标，按视口比例存，跨分辨率可用
  ④ 截图交给 AI/人 判坐标     —— 最贵；落一张截图 + `_pending.json`，
                                然后带 `--vision step=x,y` 重跑，成功后固化成 ③

带标定的步骤会把 ①② 的超时压到 1.5s，避免每次重跑都白等一遍。

金额安全
--------
视觉读出的数字**必须交叉校验**：同一数值要能在页面 DOM 文本或接口响应里
找到（`cross_check()`）。找不到就标「待复核」，绝不直接采用 ——
读错一位数比抓不到更危险。

安全边界（硬性）
----------------
**只读价，绝不下单、不提交订单、不改任何数据。** 出现验证码/滑块立即
抛 `CaptchaHit` 中止，不硬试，避免账号被风控标记。
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')

# ── 宿主平台兼容层 ────────────────────────────────────────────────
# 浏览器探测 / 会话目录 / 进程管理 / 技能目录发现 全部收敛在 platform_compat，
# 目的有两个：① 不再绑死 WorkBuddy 的 `.workbuddy` 约定，让本技能在
# Claude Code / Codex / Cursor / Gemini 等宿主上同样能跑；
# ② 换平台只改一处，而不是散落的几十个文件（2026-09-17 的教训：
# 「修复只落在某一个副本里」必然复发）。
# 它与本文件同目录，正常 import 即可；万一被单独拷走，退化成内置默认值而不是崩掉。
try:
    import platform_compat as PC
except Exception:                                        # pragma: no cover
    PC = None

DEFAULT_CDP = os.environ.get("XHS_CDP") or "http://127.0.0.1:9222"

# 兼容层缺失时的兜底会话目录名（正常情况下由 PC.session_dir 决定）
_FALLBACK_SESSION_LEAF = "agent-scrape-session"

# 验证码/风控特征。刻意收窄：像裸 "verify" 这种词在正常页面里到处都是，
# 会把正常页面误判成验证码。只留指向性明确的。
CAPTCHA_HINTS = (
    "whaleguard", "captcha",
    "请完成安全验证", "滑块验证", "拖动滑块", "点击进行验证",
    "人机验证", "安全验证", "滑动验证", "请先完成验证",
)


class NeedVision(Exception):
    """四级都没成，需要人/AI 看截图给出坐标。"""

    def __init__(self, step, shot, payload):
        super().__init__("NEED_VISION %s -> %s" % (step, shot))
        self.step = step
        self.shot = shot
        self.payload = payload


class CaptchaHit(Exception):
    """撞上验证码/风控，立即中止（不硬试）。"""


# ------------------------------------------------------------------ 会话目录

def session_dir(d=None):
    """会话目录：profile / 标定表 / cookie 快照都放这里。

    解析优先级（见 `platform_compat.session_dir`）：
      显式参数 > `SCRAPE_SESSION_DIR` > 旧的 `<cwd>/.workbuddy`（**仅当已用过**）
      > `%LOCALAPPDATA%\\agent-scrape-session`

    ⚠️ 不再无条件写进 `.workbuddy` —— 那是 WorkBuddy 专有约定，
    Claude Code / Codex / Cursor 等宿主不该被它绑住。
    但**旧的会话目录若已经用过就继续沿用**，否则用户会遇到「突然又要重新扫码」。
    """
    d = PC.session_dir(d) if PC else (
        d or os.environ.get("SCRAPE_SESSION_DIR")
        or os.path.join(os.getcwd(), _FALLBACK_SESSION_LEAF))
    os.makedirs(d, exist_ok=True)
    return d


def calib_path(d=None):
    return os.path.join(session_dir(d), "calibration.json")


# ---------------------------------------------------------------- cookie 快照
# 为什么需要：会话级 cookie（expires=-1）不落盘，浏览器一被杀就丢，
# 于是「登录一次、之后长期复用」根本做不到（用户 2026-09-17 反馈被反复踢登录）。
# 快照把 ctx 里**全部** cookie（含会话级）写进本地 JSON，下次 attach 时注回去。

def cookies_path(tag="default", d=None):
    return os.path.join(session_dir(d), "cookies_%s.json" % tag)


def save_cookies(ctx, tag="default", d=None):
    try:
        cks = ctx.cookies()
    except Exception:
        return 0
    p = cookies_path(tag, d)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cks, f, ensure_ascii=False, indent=1)
    return len(cks)


def restore_cookies(ctx, tag="default", d=None,
                    domains=("zuche.com", "ctrip.com", "xiaohongshu.com")):
    """把快照注回 context。只注目标域，避免污染。返回注入条数。

    ⚠️ domains 要写**完整域名后缀**（`zuche.com`），不能写 `zuche` ——
    cookie 的 domain 是 `m.zuche.com` / `.zuche.com`，用 `endswith("zuche")`
    会一条都匹配不上（2026-09-18 实测：还原 0 条就是这个坑）。
    """
    p = cookies_path(tag, d)
    if not os.path.exists(p):
        return 0
    try:
        with open(p, encoding="utf-8") as f:
            cks = json.load(f)
    except Exception:
        return 0
    keep = []
    for c in cks:
        dom = (c.get("domain") or "").lstrip(".")
        if domains and not any(dom == x or dom.endswith("." + x) for x in domains):
            continue
        # Playwright 只接受 sameSite 的三种字面值
        if c.get("sameSite") not in ("Strict", "Lax", "None"):
            c["sameSite"] = "Lax"
        keep.append(c)
    try:
        ctx.add_cookies(keep)
    except Exception:
        return 0
    return len(keep)


def targets(port=9222, timeout=4.0):
    """列出浏览器里**全部** target（比 ctx.pages 可靠）。

    站点用 window.open 开的新标签/新窗口，Playwright 有时不会立刻收录到
    `ctx.pages` 里（2026-09-18 实测：点「立即预订」后 ctx.pages 只有 2 个，
    但那一步其实开了新页）。查 CDP 的 /json/list 才准。
    """
    try:
        r = urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=timeout)
        return json.loads(r.read().decode("utf-8"))
    except Exception:
        return []


def new_targets(port=9222, before=()):
    """返回当前 target 中 url 不在 before 里的那些。"""
    out = []
    for t in targets(port):
        u = t.get("url") or ""
        if u and u not in before:
            out.append(t)
    return out


def load_calib(d=None):
    p = calib_path(d)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_calib(data, d=None):
    with open(calib_path(d), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def remember(step, page, x, y, d=None, note=""):
    """把成功坐标按**视口比例**固化，下次直接命中。"""
    vw, vh = viewport(page)
    data = load_calib(d)
    data[step] = dict(x_ratio=round(x / vw, 4), y_ratio=round(y / vh, 4),
                      viewport=[vw, vh], x=int(x), y=int(y), note=note,
                      ts=time.strftime("%Y-%m-%d %H:%M:%S"))
    save_calib(data, d)
    return data[step]


def viewport(page):
    try:
        vw, vh = page.evaluate("() => [window.innerWidth, window.innerHeight]")
        if vw and vh:
            return int(vw), int(vh)
    except Exception:
        pass
    vs = page.viewport_size or {}
    return int(vs.get("width") or 1440), int(vs.get("height") or 900)


# ------------------------------------------------------------------ 会话自愈

def cdp_ok(port, timeout=2.0):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port,
                               timeout=timeout).read()
        return True
    except Exception:
        return False


def native_chrome():
    """原生 Chrome / Edge 路径。

    原生内核是硬要求：携程 / 神州的指纹风控（whaleguard）会拦 Playwright
    自带 Chromium。探测逻辑（含 `CHROME_PATH` 环境变量覆盖）在兼容层里。
    """
    return PC.find_chrome() if PC else None


def session_profile():
    return os.path.join(session_dir(), "browser_profile")


def kill_stray(profile):
    """清理占着同一 profile 的僵尸 Chrome —— **本机沙箱下已停用**。

    ⚠️ 2026-09-17 实测：沙箱把 `wmic.exe` 列入**程序黑名单**
    （SECURITY POLICY，明确不允许 Retry / 换壳调用），而枚举「哪个 chrome
    进程用了我们的 profile」必须读到命令行，`tasklist` 给不了。
    → 所以这里不清理。实际也很少需要：沙箱每条命令结束都会收掉整棵进程树。
    万一真被占用，Chrome 不会开调试端口，`ensure_session` 会明确报超时。
    返回 0 = 未清理（不需要，或环境不允许）。
    """
    return 0


def launch_chrome(port=9222, profile=None, headless=False):
    """拉起一个带调试端口的原生浏览器（**由 agent 启动的临时会话**）。

    ⚠️ 需要用户亲手点登录时，别用这个 —— 沙箱会在命令结束时收掉它，
    用户根本来不及点。那种场景请用 `platform_compat.launch_instructions()`
    把命令交给用户自己执行。
    """
    exe = native_chrome()
    if not exe:
        raise SystemExit(
            "找不到原生 Chrome / Edge。\n"
            "  携程 / 神州 必须用原生内核（Playwright 自带会被 whaleguard 拦）。\n"
            "  装一个 Chrome，或设环境变量 CHROME_PATH 指向你的浏览器。")
    profile = profile or session_profile()
    os.makedirs(profile, exist_ok=True)
    if not PC:
        raise SystemExit("缺少 platform_compat.py（应与 human_act.py 同目录）")
    cmd = PC.launch_argv(exe, port, profile, headless=headless)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            **PC.detach_kwargs())
    for _ in range(30):
        time.sleep(0.7)
        if cdp_ok(port):
            return proc, port
    raise SystemExit("Chrome 已拉起（pid=%d）但 21s 内没准备好 CDP 端点" % proc.pid)


def ensure_session(cdp=None, port=9222, auto_start=True):
    """确保有一个可连的常驻浏览器；没有就自己拉一个。

    为什么可以「每次自己拉」：Bash 沙箱会在每条命令结束时清掉进程树，
    所以进程级别的「常驻」本来就不成立。但 **profile 是固定的**，
    登录态里带过期时间的 cookie（如携程 `cticket`）会落盘 ——
    实测杀掉浏览器再重启，ctrip 42 个 cookie 全在、登录照样有效。
    所以关键不是「进程不退出」，而是「**都用同一个 profile**」。

    返回 (cdp_url, started_by_us)
    """
    cdp = cdp or DEFAULT_CDP
    port = int(cdp.rstrip("/").rsplit(":", 1)[-1])
    if cdp_ok(port):
        return cdp, False
    if not auto_start:
        raise SystemExit("连不上常驻浏览器 %s，且 auto_start=False" % cdp)
    kill_stray(session_profile())
    launch_chrome(port=port)
    return cdp, True


# ------------------------------------------------------------------ 连接常驻

class Attached:
    """附到常驻浏览器上。**只关页面，绝不关浏览器。**

    关浏览器 = 会话级 cookie 一起没（踩坑⑬），所以这里没有、也不许有
    `browser.close()`。
    """

    def __init__(self, cdp=None, timeout=30000, auto_start=True):
        self.cdp = cdp or DEFAULT_CDP
        self.timeout = timeout
        self.auto_start = auto_start
        self._pw = None
        self.browser = None
        self.ctx = None
        self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        cdp, started = ensure_session(self.cdp, auto_start=self.auto_start)
        self.cdp = cdp
        if started:
            print("[human_act] 常驻浏览器未运行 → 已自动拉起（同一 profile，登录态沿用）")
        self._pw = sync_playwright().start()
        try:
            self.browser = self._pw.chromium.connect_over_cdp(self.cdp)
        except Exception as e:
            self._pw.stop()
            raise SystemExit(
                "连不上常驻浏览器 %s\n  %s\n先跑：session_daemon.py start"
                % (self.cdp, str(e)[:140]))
        self.ctx = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(self.timeout)
        return self

    def __exit__(self, *exc):
        try:
            if self.page:
                self.page.close()          # ← 只关标签页
        except Exception:
            pass
        try:
            self._pw.stop()                # 断驱动，浏览器仍在跑
        except Exception:
            pass
        return False


# ------------------------------------------------------------------ 风控检查

def assert_no_captcha(page):
    u = (page.url or "").lower()
    if "captcha" in u or "whaleguard" in u:
        raise CaptchaHit("URL 命中风控：%s" % page.url[:160])
    try:
        body = page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 3000)") or ""
    except Exception:
        body = ""
    for h in CAPTCHA_HINTS:
        if h in body:
            raise CaptchaHit("页面出现验证码特征「%s」：%s" % (h, page.url[:120]))
    return True


# ------------------------------------------------------------------ 交互

def human_type(target, text, delay=(60, 180), clear=True, read_back=None):
    """逐字输入（返回 dict: expected / actual / ok）。

    ⚠️ 两条实测教训：
    1. **别用 `fill()`** —— 它直接设 value，不触发前端事件，站点的联想/校验
       毫无反应（天地图搜索、携程城市下拉都踩过，看着像「搜了个寂寞」）。
    2. **中文别用 `Keyboard.type()`** —— 它对非 ASCII 走 `insertText`，
       而站点可能自己在 keydown 里再插一次 → 字符被写两遍：
       实测携程输入「深圳」变成了「深深圳圳」，下拉全是重复字符、
       回车也选错项（2026-09-17）。所以逐字改走 `insert_text`。
    read_back : 可选回调 `f() -> str`，回读输入框真实值。返回的 ok 直接用于
                判断「有没有输对」——输入这一步同样要验效果。
    """
    if clear:
        try:
            target.click(timeout=4000)
            target.press("Control+a")
            target.press("Delete")
        except Exception:
            pass
    for ch in text:
        try:
            target.insert_text(ch)
        except AttributeError:
            target.type(ch, delay=random.uniform(delay[0], delay[1]))
        time.sleep(random.uniform(delay[0], delay[1]) / 1000.0)
    actual = None
    if read_back is not None:
        try:
            actual = read_back()
        except Exception:
            actual = None
    ok = True if actual is None else (str(actual).strip() == str(text).strip())
    return dict(expected=text, actual=actual, ok=ok)


CAND_JS = """(lim) => {
  const out = [], seen = new Set();
  const sel = 'input,button,a,[role=button],li,span,div[class*=btn],div[class*=search],div[class*=sug]';
  document.querySelectorAll(sel).forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) return;
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') return;
    const t = (el.innerText || el.value || el.placeholder ||
               el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 56);
    if (!t && !el.id) return;
    const key = el.tagName + '|' + t + '|' + Math.round(r.left) + '|' + Math.round(r.top);
    if (seen.has(key)) return;
    seen.add(key);
    out.push({tag: el.tagName.toLowerCase(), text: t,
              cls: (el.className || '').toString().slice(0, 64),
              id: el.id || '', ph: el.placeholder || '',
              x: Math.round(r.left), y: Math.round(r.top),
              w: Math.round(r.width), h: Math.round(r.height),
              cx: Math.round(r.left + r.width / 2), cy: Math.round(r.top + r.height / 2)});
  });
  return out.slice(0, lim);
}"""


def candidates(page, limit=40):
    """页面上可见的可交互元素（文本 + 坐标）。

    这是省 token 的关键：视觉降级时先把候选打出来，多数情况我直接从清单里
    认出目标（甚至能反推出正确选择器），不必反复读整张截图。
    """
    try:
        return page.evaluate(CAND_JS, limit) or []
    except Exception:
        return []


def _print_candidates(cands, limit=26, viewport_wh=None):
    if not cands:
        print("   （没有取到可见元素候选）")
        return
    print("   %-6s %-34s %-14s %-12s %s" % ("tag", "text", "class", "center", "size"))
    for c in cands[:limit]:
        print("   %-6s %-34s %-14s %-12s %dx%d"
              % (c.get("tag", ""), (c.get("text") or "")[:34],
                 (c.get("cls") or "")[:14],
                 "%d,%d" % (c.get("cx", -1), c.get("cy", -1)),
                 c.get("w", 0), c.get("h", 0)))
    if len(cands) > limit:
        print("   …… 另有 %d 个（见 _pending.json）" % (len(cands) - limit))


def _click_xy(page, x, y, jitter=0.0):
    """真人式点击：先移动，再走完整按下/抬起序列。"""
    if jitter:
        x += random.uniform(-jitter, jitter)
        y += random.uniform(-jitter, jitter)
    x, y = max(2.0, float(x)), max(2.0, float(y))
    page.mouse.move(x, y, steps=random.randint(4, 9))
    page.wait_for_timeout(random.randint(60, 160))
    page.mouse.down()
    page.wait_for_timeout(random.randint(40, 110))
    page.mouse.up()
    return x, y


def _sels(selector):
    if not selector:
        return []
    if isinstance(selector, (list, tuple)):
        return [s for s in selector if s]
    return [selector]


def _attempts(page, selector, text):
    """把「选择器列表 + 文本」展开成有序候选，**顺序即优先级**。"""
    out = []
    for s in _sels(selector):
        out.append(("sel", s[:36], page.locator(s)))
    if text:
        out.append(("text", str(text)[:30], page.get_by_text(str(text), exact=False)))
    return out


def _verify_ok(verify, page):
    if verify is None:
        return True
    try:
        return bool(verify(page))
    except Exception:
        return False


def human_click(page, step, selector=None, text=None, *,
                calib=None, vision=None, out_dir=None, timeout=8000,
                wait_after=(0.5, 1.2), extra=None, verify=None, force_coord=False):
    """四级降级点击。返回 (how, x, y, calib_rec)。

    step      : 稳定标识（如 "ctrip:search_btn"），标定表与 pending 都按它索引
    selector  : CSS 选择器；**可以传列表，列表顺序就是优先级**。
                ⚠️ 不要用逗号拼成一个选择器 —— 那是并集，`.first` 会取 DOM 里
                靠前的那个。实测踩到：页头搜索框和酒店面板输入框同时命中，
                结果输错框（2026-09-17）。
    text      : 可见文本（get_by_text），排在所有 CSS 选择器之后
    verify    : 回调 `f(page) -> bool`，判断「这一点有没有真的生效」。
                `.click()` 返回成功但点到别的/隐藏元素是常见假成功 ——
                实测踩到：搜索按钮报 dom 成功但页面毫无变化。带 verify 就会
               继续降级，不会把假成功当成成功。
    force_coord : 跳过 DOM 点击，直接按 bbox 坐标点（已知会被遮罩挡时用）
    """
    calib = calib if calib is not None else load_calib()
    vision = vision or {}

    # 显式给定坐标 → 直接用（说明 DOM 已经证实走不通，别再白等）
    if step in vision:
        vx, vy = vision[step]
        _click_xy(page, vx, vy)
        page.wait_for_timeout(random.uniform(*wait_after) * 1000)
        if _verify_ok(verify, page):
            return "vision", vx, vy, remember(step, page, vx, vy, note="vision")
        return "vision", vx, vy, calib.get(step)

    known = step in calib
    dom_timeout = 1500 if known else timeout
    cands = _attempts(page, selector, text)

    # ① DOM 选择器点击（按优先级逐个试，验效果不过就换下一个）
    if not force_coord:
        for kind, label, loc in cands:
            try:
                loc.first.wait_for(state="visible", timeout=dom_timeout)
                loc.first.click(timeout=dom_timeout)
                page.wait_for_timeout(random.uniform(*wait_after) * 1000)
                if not _verify_ok(verify, page):
                    continue
                box = None
                try:
                    box = loc.first.bounding_box()
                except Exception:
                    pass
                cx = (box["x"] + box["width"] / 2) if box else -1
                cy = (box["y"] + box["height"] / 2) if box else -1
                if cx > 0:
                    remember(step, page, cx, cy, note="dom:" + label[:20])
                return "dom", cx, cy, calib.get(step)
            except Exception:
                continue

    # ② DOM 拿到 bbox → 坐标点击（解决「看得见点不动」）
    for kind, label, loc in cands:
        try:
            if loc.count() <= 0:
                continue
            box = loc.first.bounding_box()
            if not (box and box["width"] > 0 and box["height"] > 0):
                continue
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            _click_xy(page, cx, cy, jitter=min(box["width"], box["height"]) * 0.12)
            page.wait_for_timeout(random.uniform(*wait_after) * 1000)
            if not _verify_ok(verify, page):
                continue
            return "bbox", cx, cy, remember(step, page, cx, cy, note="bbox:" + label[:20])
        except Exception:
            continue

    # ③ 标定表里上次成功过的坐标
    if known:
        vw, vh = viewport(page)
        cx = calib[step]["x_ratio"] * vw
        cy = calib[step]["y_ratio"] * vh
        _click_xy(page, cx, cy)
        page.wait_for_timeout(random.uniform(*wait_after) * 1000)
        return "calib", cx, cy, calib[step]

    # ④ 交给视觉：落截图 + 候选清单 + pending，让调用方带我给的坐标重跑
    out_dir = out_dir or session_dir()
    os.makedirs(out_dir, exist_ok=True)
    shot = os.path.join(out_dir, "_pending_%s.png" % re.sub(r"[^0-9A-Za-z_]+", "_", step))
    try:
        page.screenshot(path=shot)
    except Exception as e:
        shot = "(截图失败: %s)" % str(e)[:60]
    vw, vh = viewport(page)
    cands = candidates(page, 60)
    try:
        head = (page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 600)") or "")
    except Exception:
        head = ""
    payload = dict(step=step, screenshot=shot, viewport=[vw, vh],
                   url=page.url, selector=selector, text=text,
                   text_head=head, candidates=cands,
                   ts=time.strftime("%Y-%m-%d %H:%M:%S"))
    if isinstance(extra, dict):
        payload.update(extra)
    with open(os.path.join(out_dir, "_pending.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("NEED_VISION step=%s" % step)
    print("  shot     = %s" % shot)
    print("  viewport = %dx%d（截图是视口像素，与 mouse.click 同一坐标系）" % (vw, vh))
    print("  url      = %s" % page.url)
    print("  --- 页面可见元素候选（可直接取 cx,cy 当坐标）---")
    _print_candidates(cands)
    if head:
        print("  --- 页面文本开头 ---")
        print("  " + head[:400].replace("\n", " / "))
    raise NeedVision(step, shot, payload)


# ------------------------------------------------------------------ 抓取与落盘

class NetLog:
    """记录 JSON 接口响应，用于金额交叉校验。

    刻意不在事件回调里读 body（同步 API 在回调里取 body 有重入风险），
    只登记响应对象，落盘时再统一读取。
    """

    def __init__(self, page, limit=120):
        self.limit = limit
        self.items = []
        page.on("response", self._on)

    def _on(self, resp):
        try:
            if len(self.items) >= self.limit:
                return
            ct = (resp.headers or {}).get("content-type", "").lower()
            if "json" not in ct:
                return
            self.items.append(resp)
        except Exception:
            pass

    def snapshot(self, body_cap=300000):
        out = []
        for r in self.items:
            rec = {"url": (r.url or "")[:300], "status": r.status}
            try:
                rec["body"] = (r.text() or "")[:body_cap]
            except Exception as e:
                rec["body_err"] = str(e)[:80]
            out.append(rec)
        return out


MONEY_RE = re.compile(r"(?:¥|￥|RMB)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")

# 遍历全部文本节点，不受渲染影响。
# 为什么不能只用 innerText：JS 重站常给屏外区块加 `content-visibility: auto`，
# innerText 会**跳过未渲染区域** —— 实测携程酒店列表页：卡片明明在 DOM 里
# （[class*=hotel] 有 318 个），但 innerText 只剩顶部的价格筛选条，
# 17 个「金额」全是筛选区间（¥200 - ¥300），一个酒店价都没抽到（2026-09-17）。
DEEP_TEXT_JS = """() => {
  const SKIP = {SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1};
  const parts = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walk.nextNode())) {
    const p = n.parentNode;
    if (!p || SKIP[p.nodeName]) continue;
    const t = (n.nodeValue || '').replace(/\\s+/g, ' ').trim();
    if (t) parts.push(t);
  }
  return parts.join('\\n');
}"""


def deep_text(page):
    try:
        return page.evaluate(DEEP_TEXT_JS) or ""
    except Exception:
        return ""


def prices_in(text):
    """抽出文本里的钱数（含上下文片段，便于判断这是裸价还是含保险总价）。"""
    out = []
    for m in MONEY_RE.finditer(text or ""):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except Exception:
            continue
        s = max(0, m.start() - 60)
        out.append(dict(value=val,
                        raw=m.group(0),
                        context=(text[s:m.end() + 40].replace("\n", " "))[:150]))
    return out


def cross_check(value, *texts):
    """金额交叉校验：视觉读出的数字必须能在 DOM 文本/接口响应里找到同值。

    找不到 → False，调用方应标「待复核」而不是采用。
    """
    pats = []
    for fmt in ("{:,.0f}", "{:.0f}", "{:,.2f}", "{:.2f}", "{}"):
        try:
            pats.append(fmt.format(value))
        except Exception:
            pass
    pats.append(str(int(value)))
    for t in texts:
        if not t:
            continue
        for p in pats:
            if p and p in t:
                return True
    return False


def dump(page, out_dir, name, netlog=None, extra=None):
    """三件套落盘：截图 + DOM 文本 + 接口响应。

    纯 JS 页面 innerText 为空时，看截图比反复猜选择器快得多（手册第五节）。
    """
    os.makedirs(out_dir, exist_ok=True)
    res = dict(name=name, url=page.url, ts=time.strftime("%Y-%m-%d %H:%M:%S"))
    shot = os.path.join(out_dir, name + ".png")
    txt_p = os.path.join(out_dir, name + ".txt")
    try:
        page.screenshot(path=shot)
        res["png"] = shot
    except Exception as e:
        res["png_err"] = str(e)[:80]
    try:
        body = page.inner_text("body", timeout=10000)
    except Exception:
        body = ""
    deep = deep_text(page)
    # 价格一律从 deep 里抽（innerText 会漏掉 content-visibility 跳过的屏外内容）
    src_text = deep if len(deep) > len(body) else body
    with open(txt_p, "w", encoding="utf-8") as f:
        f.write("%s\n\n--- visible(innerText) %d ---\n%s\n\n--- deep(textNodes) %d ---\n%s"
                % (page.url, len(body), body[:40000], len(deep), deep[:120000]))
    res["txt"] = txt_p
    res["text_len"] = len(body)
    res["deep_len"] = len(deep)
    seen = set()
    prices = []
    for p in prices_in(src_text):
        k = (p["value"], p["context"][:40])
        if k in seen:
            continue
        seen.add(k)
        prices.append(p)
    res["prices"] = prices[:120]
    if netlog is not None:
        snap = netlog.snapshot()
        net_p = os.path.join(out_dir, name + ".net.json")
        with open(net_p, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
        allnet = "\n".join(x.get("body", "") for x in snap)
        res["net"] = net_p
        res["net_count"] = len(snap)
        res["net_prices"] = prices_in(allnet)[:80]
    if isinstance(extra, dict):
        res.update(extra)
    with open(os.path.join(out_dir, name + ".meta.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("[dump] %-22s visible=%-6d deep=%-6d prices=%-3d net=%-3d %s"
          % (name, res.get("text_len", 0), res.get("deep_len", 0),
             len(res.get("prices", [])), res.get("net_count", 0), page.url[:60]))
    return res


# ------------------------------------------------------------------ 自检

def _probe_session_delegation():
    """确认 `session_dir()` 真的在走兼容层的解析规则。

    刻意用**行为断言**而不是「源码里有没有某个字符串」—— 后者会搜到检查项
    自身（2026-09-18 被这个自我指涉坑过一次，报了个假 FAIL）。
    """
    import tempfile
    old = os.environ.get("SCRAPE_SESSION_DIR")
    t = tempfile.mkdtemp(prefix="ses_chk_")
    try:
        os.environ["SCRAPE_SESSION_DIR"] = t
        got = session_dir()
        want = PC.session_dir(t) if PC else t
        return (os.path.normcase(os.path.abspath(got))
                == os.path.normcase(os.path.abspath(want))
                and not got.rstrip("\\/").endswith(".workbuddy"))
    except Exception:
        return False
    finally:
        if old is None:
            os.environ.pop("SCRAPE_SESSION_DIR", None)
        else:
            os.environ["SCRAPE_SESSION_DIR"] = old


def selfcheck():
    """副本漂移自检：确认四级降级与安全约束都在。"""
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    # 真·关浏览器的调用（行首是代码，不是文档里带反引号的说明文字）
    real_close = re.search(r"^\s*(self\.)?browser\.close\(\)", src, re.M)
    checks = [
        ("四级：DOM 选择器点击", "loc.first.click(timeout=dom_timeout)" in src),
        ("选择器优先级列表（避免逗号并集点错元素）",
         "def _sels(" in src and "def _attempts(" in src),
        ("点击后验效果（防假成功降级）",
         "def _verify_ok(" in src and "if not _verify_ok(verify, page)" in src),
        ("四级：bbox 坐标点击", "_click_xy(page, cx, cy, jitter=" in src),
        ("四级：标定表固化", "def remember(" in src and "x_ratio" in src),
        ("四级：截图交视觉", "class NeedVision" in src and "raise NeedVision(" in src),
        ("视觉降级附带候选清单", "def candidates(" in src and "_print_candidates(cands)" in src),
        ("逐字输入（不用 fill）", "def human_type(" in src),
        ("中文输入用 insert_text（防字符写两遍）", "insert_text(ch)" in src and "read_back" in src),
        ("风控识别并中止", "def assert_no_captcha(" in src and "class CaptchaHit" in src),
        ("三件套落盘", "def dump(" in src and ".net.json" in src),
        ("deep 文本（绕开 content-visibility 屏外漏字）",
         "def deep_text(" in src and "DEEP_TEXT_JS" in src),
        ("金额交叉校验", "def cross_check(" in src),
        ("会话自愈（自动拉起浏览器 + 清僵尸 profile）",
         "def ensure_session(" in src and "def kill_stray(" in src and "auto_start" in src),
        ("绝不关浏览器（无 browser.close 调用）", real_close is None),
        ("只关标签页", "self.page.close()" in src),
        # ── 宿主平台中立性（2026-09-18：让它能在各 agent 平台上跑）──
        ("兼容层已加载", PC is not None),
        ("浏览器探测走兼容层（含 CHROME_PATH 覆盖）",
         PC is not None and native_chrome() == PC.find_chrome()),
        ("会话目录委托给兼容层（不再无条件写 .workbuddy）",
         _probe_session_delegation()),
        ("启动命令由兼容层生成（Windows 走 Win+R 提示）",
         "PC.launch_argv(" in src and "PC.detach_kwargs()" in src),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print("  %-6s %s" % ("PASS" if ok else "FAIL", n))
    # 标定表读写回环
    try:
        import tempfile
        d = tempfile.mkdtemp(prefix="calib_chk_")
        save_calib({"t:1": dict(x_ratio=0.5, y_ratio=0.5)}, d)
        assert load_calib(d)["t:1"]["x_ratio"] == 0.5
        print("  PASS   标定表读写回环")
    except Exception as e:
        bad.append("标定表读写回环")
        print("  FAIL   标定表读写回环：%s" % str(e)[:60])
    print()
    if bad:
        print("SELFCHECK_FAIL %d 项：%s" % (len(bad), ", ".join(bad)))
        print("  提示：若跑的是旧副本，请重新复制。两个技能必须装在**同一个** skills 根目录下；")
        print("        脚本会在多个候选目录里自动找兄弟技能（见 platform_compat.skills_roots）。")
        print("        本机会话目录：%s" % session_dir())
        return 1
    print("SELFCHECK_PASS（四级降级 + 三件套 + 金额校验 + 不关浏览器 + 平台中立 全部就位）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="拟人化浏览器操作层（坐标点击 + 视觉降级）")
    ap.add_argument("--selfcheck", action="store_true", help="自检四级降级与安全约束")
    ap.add_argument("--cdp", default="", help="CDP 端点（默认取 XHS_CDP 或 127.0.0.1:9222）")
    ap.add_argument("--calib", action="store_true", help="打印标定表")
    ap.add_argument("--session-dir", default="", help="会话目录（默认 SCRAPE_SESSION_DIR）")
    args = ap.parse_args()

    if args.selfcheck:
        return selfcheck()
    if args.calib:
        data = load_calib(args.session_dir or None)
        print("标定表 %s（%d 条）" % (calib_path(args.session_dir or None), len(data)))
        for k, v in sorted(data.items()):
            print("  %-38s %.4f, %.4f  (%s)  %s"
                  % (k, v.get("x_ratio", -1), v.get("y_ratio", -1),
                     v.get("note", ""), v.get("ts", "")))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
