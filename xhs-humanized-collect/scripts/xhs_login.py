# -*- coding: utf-8 -*-
"""小红书扫码登录（登录态长期复用）。

用法:
  # ① 推荐：连常驻会话登录 —— 扫完码浏览器不退出，登录态一直活着
  python session_daemon.py start
  XHS_CDP=http://127.0.0.1:9222 python xhs_login.py

  # ② 独立模式（会关浏览器）：只在调试时用
  python xhs_login.py

⚠️ 为什么推荐常驻（2026-09-17 用户明确要求）
-------------------------------------------
**浏览器一关，会话 cookie 就带走了。** 站点登录态里含会话级 cookie（无过期时间、
只在内存），`browser.close()` 之后不会落盘进 profile 的 cookie 库 ——
下次重新 launch 就是「已退出登录」，于是每次采集都要重新扫码；
而**高频登录本身就会触发风控**（比采集更容易被拦）。
所以：登录要在常驻会话里做（`XHS_CDP` 模式），扫完码谁都不许关浏览器，
采集脚本通过 CDP 接着用同一个会话。

成功输出: LOGIN_SUCCESS / COOKIES_SAVED / RESIDENT_KEPT_ALIVE
未按提示扫码: LOGIN_TIMEOUT_5MIN
"""
import sys, time, json, os
from playwright.sync_api import sync_playwright

# ===== 配置区（按需修改）=====
BASE_DIR = os.environ.get("XHS_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(BASE_DIR, "xhs_profile")
COOKIES = os.path.join(BASE_DIR, "xhs_cookies.json")
HOME = "https://www.xiaohongshu.com"
# 登录按钮选择器（多选择器回退，站点改版时 F12 补充）
LOGIN_SELECTORS = [".side-bar-component .login-btn", ".login-btn", "text=登录"]
# 常驻会话端点：设置后走「连接常驻浏览器」模式，不再自己 launch/close
CDP = os.environ.get("XHS_CDP", "").strip()
# ============================


def login_btn_gone(page):
    """真实登录判据：登录按钮不存在 或 不可见。
    注意：不能用 web_session cookie 判断 —— 匿名会话也带 web_session。"""
    for sel in LOGIN_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return False
        except Exception:
            continue
    return True


def save_cookies(browser):
    cookies = browser.cookies()
    with open(COOKIES, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=1)


def finish(ok, ctx, browser, page, code):
    """收尾：永远不关常驻浏览器。

    · 常驻模式（XHS_CDP）：只关本次打开的标签页 → 会话与 cookie 留在常驻进程里
    · 独立模式：会关浏览器，因此**登录态基本留不住**，只能靠上面的 cookies.json
      兜底（很多站点不接受纯 cookie 复放）—— 所以独立模式只用于调试
    """
    try:
        save_cookies(ctx)
    except Exception:
        pass
    if CDP:
        try:
            page.close()
        except Exception:
            pass
        print("RESIDENT_KEPT_ALIVE 浏览器保持运行（未关闭）—— 采集脚本可直接复用该会话")
        print("  提示：本次抓取任务全部做完之前，不要执行 session_daemon.py stop")
    else:
        try:
            ctx.close()
        except Exception:
            pass
        print("!! 独立模式已关闭浏览器：会话 cookie 会随之丢失，"
              "下次采集大概率要重新扫码。建议改用 XHS_CDP 常驻模式。")
    sys.exit(code)


with sync_playwright() as p:
    if CDP:
        # 连接常驻浏览器：同一个会话，采集/登录共用，谁都不关它
        br = p.chromium.connect_over_cdp(CDP)
        ctx = br.contexts[0] if br.contexts else br.new_context()
        page = ctx.new_page()
        print("ATTACHED 常驻会话 %s" % CDP)
    else:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    if login_btn_gone(page):
        print("ALREADY_LOGGED_IN")
        save_cookies(ctx)
        finish(True, ctx, None, page, 0)

    # 点击登录按钮，弹出二维码
    for sel in LOGIN_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=3000)
                break
        except Exception:
            continue
    page.wait_for_timeout(2000)

    # 确保二维码 tab 可见
    try:
        qr_tab = page.locator("text=扫码登录").first
        if qr_tab.count() > 0 and qr_tab.is_visible():
            qr_tab.click(timeout=2000)
            page.wait_for_timeout(1000)
    except Exception:
        pass

    print("QR_READY 浏览器窗口已弹出登录二维码，请用小红书App扫码...")
    sys.stdout.flush()

    deadline = time.time() + 300
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        if login_btn_gone(page):
            page.wait_for_timeout(2500)  # 等登录态稳定，需二次确认防止瞬时误判
            if login_btn_gone(page):
                print("LOGIN_SUCCESS")
                save_cookies(ctx)
                print("COOKIES_SAVED（仅作备份；真正的登录态在常驻浏览器里）")
                finish(True, ctx, None, page, 0)

    print("LOGIN_TIMEOUT_5MIN")
    finish(False, ctx, None, page, 1)
