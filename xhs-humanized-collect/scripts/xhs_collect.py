# -*- coding: utf-8 -*-
"""
小红书拟人化采集：按关键词搜索 → 点开笔记 → 提取正文 → 存 JSONL。

用法:
    python xhs_collect.py           # 从头跑
    python xhs_collect.py 12        # 从第 13 个关键词断点续跑

反爬要点（改脚本时别破坏这几条）:
  1. headless=False + 真实 viewport         —— headless 是重点检测对象
  2. --disable-blink-features=AutomationControlled —— 去掉 navigator.webdriver
  3. 全程 UI 点击，不调接口
  4. human_wait 用 random.uniform 随机延迟，不用固定 sleep
  5. per_query 默认 5，词间休息 1.5-3s，整体约 8s/帖
出现滑块立刻停 10 分钟，硬闯会升级为封号。
"""
import json, time, random, sys, os, re, urllib.parse
from playwright.sync_api import sync_playwright

# ===== 配置区（按需修改）=====
BASE_DIR = os.environ.get("XHS_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(BASE_DIR, "xhs_profile")
OUT = os.path.join(BASE_DIR, "xhs_notes.jsonl")
LOG = os.path.join(BASE_DIR, "xhs_collect.log")

QUERIES = [
    # 在此填入你的关键词，建议按主题分组（每组 2-5 个词），20-30 个词为宜
    "示例关键词一",
    "示例关键词二",
]
# ==============================

HOME = "https://www.xiaohongshu.com"
LOGIN_SELECTORS = [".side-bar-component .login-btn", ".login-btn", "text=登录"]
CARD_SELECTOR = "section.note-item"
TEXT_SELECTORS = [".note-text", "#detail-desc", ".desc"]

# 正文补强相关
EXPAND_SELECTORS = ["text=展开", ".note-text .expand", "text=…展开", "text=全文"]
COMMENT_SELECTOR = ".comment-item"
COMMENT_LIMIT = 10          # 每帖最多抓几条评论（问答类帖子答案常在评论区）
GRAB_COMMENTS = True        # 不需要评论时关掉可提速


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def human_wait(a=1.2, b=2.6):
    """随机延迟 —— 固定 sleep 会被节奏指纹识别"""
    time.sleep(random.uniform(a, b))


def close_popups(page):
    for sel in [".close", '[class*="close"]']:
        try:
            loc = page.locator(sel)
            for i in range(min(loc.count(), 3)):
                if loc.nth(i).is_visible():
                    loc.nth(i).click(timeout=1000)
                    break
        except Exception:
            pass


def expand_full_text(page):
    """
    点「展开全文」。
    实测：多数小红书笔记的 DOM 里 .note-text 已经是全文，
    「展开」只是 CSS line-clamp 的视觉截断，不点也能拿到完整文本。
    但少数长帖确实需要点击，所以保留这一步作为保险。
    """
    for sel in EXPAND_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=1500)
                page.wait_for_timeout(600)
                return True
        except Exception:
            continue
    return False


def is_tag_only(text):
    """判断是否为「纯话题标签帖」——正文只有 #xxx，无实质内容"""
    if not text.strip():
        return False
    body = re.sub(r"#\S+", "", text).strip()
    return "#" in text and len(body) == 0


def collect_comments(page, limit=COMMENT_LIMIT):
    """
    抓评论区。问答类帖子（如「推荐个干净的民宿呗」）的精华答案常在评论区，
    只抓正文会拿到一堆标签 + 零信息。
    """
    out = []
    if not GRAB_COMMENTS:
        return out
    try:
        loc = page.locator(COMMENT_SELECTOR)
        n = min(loc.count(), limit)
        for i in range(n):
            try:
                t = loc.nth(i).inner_text(timeout=1500).strip()
                if t:
                    out.append(t)
            except Exception:
                continue
    except Exception:
        pass
    return out


def collect_query(page, kw, per_query=5):
    url = HOME + "/search_result?keyword=" + urllib.parse.quote(kw)
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500 + random.uniform(500, 1500))
    results = []
    try:
        page.wait_for_selector(CARD_SELECTOR, timeout=12000)
    except Exception:
        log(f"  !! 无笔记卡片: {kw}")
        return results

    count = page.locator(CARD_SELECTOR).count()
    log(f"  搜索[{kw}] 卡片数={count}")
    n = min(per_query, count)
    for i in range(n):
        try:
            card = page.locator(CARD_SELECTOR).nth(i)
            title = card.locator(".title").first.inner_text(timeout=3000).strip() if card.locator(".title").count() else ""
            author = ""
            if card.locator(".author .name").count():
                author = card.locator(".author .name").first.inner_text(timeout=2000).strip()
            likes = ""
            if card.locator(".like-wrapper .count").count():
                likes = card.locator(".like-wrapper .count").first.inner_text(timeout=2000).strip()
            href = card.locator("a").first.get_attribute("href", timeout=3000) or ""

            card.click(timeout=5000)
            page.wait_for_timeout(1800 + random.uniform(300, 900))

            # 先尝试点开「展开全文」，再抽正文（DOM 多数已是全文，此步是保险）
            expand_full_text(page)
            text = ""
            for sel in TEXT_SELECTORS:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    text = loc.first.inner_text(timeout=4000).strip()
                    if text:
                        break

            date = ""
            try:
                if page.locator(".date").count():
                    date = page.locator(".date").first.inner_text(timeout=1500).strip()
            except Exception:
                pass

            if title or text:
                comments = collect_comments(page) if is_tag_only(text) or len(text) < 80 else []
                results.append({"query": kw, "title": title, "author": author,
                                "likes": likes, "url": href, "date": date,
                                "text": text[:3000],
                                "tag_only": is_tag_only(text),
                                "comments": comments})
                flag = " [纯标签帖]" if is_tag_only(text) else ""
                cflag = f" +{len(comments)}评" if comments else ""
                log(f"    [{i+1}/{n}] {title[:40]} 赞={likes} 正文{len(text)}字{flag}{cflag}")

            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            human_wait(1.0, 2.0)
        except Exception as e:
            log(f"    [{i+1}/{n}] 单帖异常: {str(e)[:80]}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            human_wait(0.8, 1.5)
    return results


def main():
    start_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            PROFILE, headless=False,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # 登录校验 —— 登录态失效会导致后续全部静默失败，必须在开头挡住
        for sel in LOGIN_SELECTORS:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    log("!! 登录态失效，请先运行 xhs_login.py")
                    browser.close()
                    sys.exit(2)
            except Exception:
                continue

        total = 0
        for qi, kw in enumerate(QUERIES[start_idx:], start_idx):
            log(f"({qi+1}/{len(QUERIES)}) 开始: {kw}")
            rows = collect_query(page, kw)
            with open(OUT, "a", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += len(rows)
            log(f"  累计采集 {total} 篇")
            human_wait(1.5, 3.0)
        log(f"完成，共 {total} 篇")
        browser.close()


if __name__ == "__main__":
    main()
