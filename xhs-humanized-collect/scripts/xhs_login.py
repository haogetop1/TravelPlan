# -*- coding: utf-8 -*-
"""
小红书扫码登录（只需执行一次，登录态长期复用于 xhs_profile）。

用法:  python xhs_login.py
成功输出: LOGIN_SUCCESS / COOKIES_SAVED
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


with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        PROFILE, headless=False,
        viewport={"width": 1440, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = browser.pages[0] if browser.pages else browser.new_page()
    page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    if login_btn_gone(page):
        print("ALREADY_LOGGED_IN")
        save_cookies(browser)
        browser.close()
        sys.exit(0)

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
                save_cookies(browser)
                print("COOKIES_SAVED")
                browser.close()
                sys.exit(0)

    print("LOGIN_TIMEOUT_5MIN")
    browser.close()
