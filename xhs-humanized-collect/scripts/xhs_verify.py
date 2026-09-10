# -*- coding: utf-8 -*-
"""
校验当前 profile 是否处于真实登录态（排查采集静默失败时第一步就跑这个）。

用法:  python xhs_verify.py
输出:  LOGGED_IN 或 NOT_LOGGED_IN（附 cookie 明细，用于排查）
"""
import os, sys
from playwright.sync_api import sync_playwright

BASE_DIR = os.environ.get("XHS_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(BASE_DIR, "xhs_profile")
HOME = "https://www.xiaohongshu.com"
LOGIN_SELECTORS = [".side-bar-component .login-btn", ".login-btn", "text=登录"]


def login_btn_gone(page):
    for sel in LOGIN_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return False
        except Exception:
            continue
    return True


with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        PROFILE, headless=False,
        viewport={"width": 1440, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = browser.pages[0] if browser.pages else browser.new_page()
    page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    ok = login_btn_gone(page)
    print("LOGGED_IN" if ok else "NOT_LOGGED_IN")

    # 打印关键 cookie，便于排查（注意：web_session 在匿名会话中也存在，不能作为登录标志）
    names = {c["name"] for c in browser.cookies()}
    for k in ["web_session", "a1", "webId", "gid", "customerClientId"]:
        print(f"  cookie[{k}] = {k in names}")

    browser.close()
    sys.exit(0 if ok else 1)
