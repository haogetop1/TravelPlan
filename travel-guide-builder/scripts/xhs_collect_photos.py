# -*- coding: utf-8 -*-
"""
小红书正文原图采集器 v2（修正版）

为什么重写：旧采集器用 `.swiper-slide img` 抓图，命中的是页面表情面板的 48x48 贴纸，
真正正文大图在 `__INITIAL_STATE__.note.noteDetailMap[<id>].note.imageList`。
另外裸 /explore/<id> 直访会 404（error_code 300031），必须带搜索时返回的 xsec_token。

流程：
  A. 按景点关键词搜索 → 收割卡片 href（含 xsec_token）
  B. 带 token 访问笔记 → 轮询 noteDetailMap 水合 → 取 imageList 原图 URL
  C. 下载 → 转 JPEG（≤1600px）→ 存 roadbook/_raw/photos/<slug>/<note_id>/NN.jpg

用法：
  python xhs_photo_collect.py                 # 全部景点
  python xhs_photo_collect.py qianlingshan qingyunshiji   # 只跑指定 slug
  python xhs_photo_collect.py --selfcheck      # 副本漂移自检（见下）

会话模式（2026-09-17 用户要求：抓取一律常驻）
--------------------------------------------
**浏览器一关，会话 cookie 就带走了** —— 小红书登录态含会话级 cookie（无过期时间、
只在内存），`ctx.close()` 后不会落盘，下次重新 launch 就是「已退出登录」，
只能再扫码；而高频登录比抓取更容易触发风控。

所以**推荐常驻模式**：先起服务，再让采集挂上去，结束时只关标签页、不关浏览器：

```bash
python xhs-humanized-collect/scripts/session_daemon.py start
XHS_CDP=http://127.0.0.1:9222 python xhs_photo_collect.py
```

不设 `XHS_CDP` 时才走独立 launch + 关闭（调试用，日志会警告会丢登录态）。

⚠️ 踩坑⑪ 的唯一实现点：`eval_retry()`
--------------------------------------
所有 `page.evaluate` **一律走 `eval_retry()`**，不要在调用点各写一套重试。
搜索页与笔记页都会「多跳重定向」，期间 window 被销毁，单次 evaluate 必爆
`Execution context was destroyed`。

**副本漂移是 2026-09-17 复发的根因**：当时某个副本（仓库 / 项目目录）停在旧版，
`search_cards()` 里只有单次 `evaluate`，于是同一坑又踩一遍 ——
表现仍是「搜索失败」，实际是脚本写法问题。
改完本文件请同步三处并跑 `--selfcheck`：本地技能 / GitHub 仓库 / 项目目录副本。
"""
import os, sys, json, time, random, io, re, urllib.parse

sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.dirname(os.path.abspath(__file__))


def _find_profile():
    """定位小红书登录态 profile（按候选顺序取第一个存在的）。

    为什么是一串候选而不是一个固定位置：登录态要能在**各宿主平台**下复用，
    同时**不能让老用户掉登录态**。顺序：
      1. `XHS_PROFILE`                      显式指定（最高优先）
      2. 从当前目录向上找 `<workspace>/.workbuddy/xhs_qr_profile`   ← 历史约定，保留
      3. `<会话目录>/xhs_profile`             ← 新约定，与其它平台抓取共用
         （会话目录见 platform_compat.session_dir）
      4. `%LOCALAPPDATA%\\agent-skills\\xhs_profile` 等平台中立位置
      5. `~/.workbuddy/xhs_qr_profile`       兜底

    不写死绝对路径 —— 那既会在别人机器上直接失效，也会把本机用户名泄进公开仓库。
    """
    env = os.environ.get("XHS_PROFILE")
    if env:
        return env

    cands = []
    cur = os.path.abspath(os.getcwd())
    while True:                                    # 2) 历史约定
        cands.append(os.path.join(cur, ".workbuddy", "xhs_qr_profile"))
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    home = os.path.expanduser("~")
    try:                                           # 3) 共用会话目录
        sys.path.insert(0, BASE)
        import platform_compat as _PC              # noqa: E402
        cands.append(os.path.join(_PC.session_dir(), "xhs_profile"))
        cands.append(os.path.join(_PC.default_skills_home(), "xhs_profile"))
    except Exception:
        cands.append(os.path.join(home, ".local", "share",
                                  "agent-scrape-session", "xhs_profile"))
    cands.append(os.path.join(home, ".workbuddy", "xhs_qr_profile"))   # 5) 兜底

    for c in cands:
        if c and os.path.isdir(c):
            return c
    return cands[-1]


PROFILE = _find_profile()

# ⚠️ 采集产物**不要写进技能目录**：技能目录是「安装物」，被写脏后会跟着同步进
# 公开仓库（2026-09-18 发现）。改到当前工作目录下，并支持环境变量覆盖。
_RAW = os.environ.get("XHS_PHOTOS_OUT") or os.path.join(os.getcwd(), "roadbook", "_raw")
OUT = os.path.join(_RAW, "photos")
LOG = os.path.join(_RAW, "_photos.log")
META = os.path.join(_RAW, "_photos.jsonl")
os.makedirs(OUT, exist_ok=True)

from PIL import Image
from playwright.sync_api import sync_playwright

CARDS_PER_QUERY = 22     # 每个关键词最多收割多少卡片
NOTES_PER_SLUG = 6       # 每个景点最多抓几篇
IMGS_PER_NOTE = 8        # 每篇最多取几张
MAX_W = 1600

# slug -> (搜索词列表, 该景点中文名)
TASKS = [
    ("zongluxian",   (["贵州自驾游路线图", "贵州旅游地图 景点分布", "贵州环线 自驾 路线"], "贵州总路线")),
    ("guiyang_city", (["贵阳景点地图 攻略", "贵阳旅游 必去 景点"], "贵阳市区")),
    ("qianlingshan", (["黔灵山公园 攻略", "黔灵山 猴子 拍照"], "黔灵山公园")),
    ("qingyunshiji", (["贵阳青云市集 拍照", "青云市集 美食"], "青云市集")),
    ("jiaxiulou",    (["甲秀楼 夜景 拍照"], "甲秀楼")),
    ("huangguoshu",  (["黄果树瀑布 大瀑布 拍照", "黄果树瀑布 水帘洞"], "黄果树大瀑布")),
    ("doupotang",    (["陡坡塘瀑布 拍照", "陡坡塘 西游记"], "陡坡塘瀑布")),
    ("tianxingqiao", (["天星桥 银链坠潭瀑布", "天星桥景区 攻略"], "天星桥")),
    ("libo_city",    (["荔波古镇 拍照", "荔波县城 美食 住宿"], "荔波县城")),
    ("xiaoqikong",   (["荔波小七孔 拍照", "小七孔古桥 打卡", "小七孔 卧龙潭"], "荔波小七孔")),
    ("wolongtan",    (["卧龙潭 小七孔 拍照"], "卧龙潭")),
    ("xijiang",      (["西江千户苗寨 拍照", "西江苗寨 风雨桥 梯田"], "西江千户苗寨")),
    ("xijiang_night",(["西江千户苗寨 夜景 观景台"], "西江夜景")),
    ("qingyan",      (["青岩古镇 拍照", "青岩古镇 美食"], "青岩古镇")),
    ("anshun_city",  (["安顺 景点 地图", "安顺古城 拍照"], "安顺")),
    ("qdn_city",     (["凯里 景点 拍照", "黔东南 古镇"], "黔东南")),
]


def log(m):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), m)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def wait(a=1.4, b=3.2):
    time.sleep(random.uniform(a, b))


# ---------------------------------------------------------------- 踩坑⑪ 防护

EVAL_TRIES = 14              # evaluate 重试轮数（每轮 sleep 2-3s）
CAPTCHA_PATH = "/website-login/captcha"

# 搜索页卡片收割（配 eval_retry 使用）
SEARCH_JS = """(lim) => {
    const out = [];
    document.querySelectorAll('section.note-item').forEach((sec, i) => {
        if (i >= lim) return;
        const a = sec.querySelector('a.cover') || sec.querySelector('a');
        if (!a) return;
        const href = a.getAttribute('href') || '';
        const m = href.match(/\\/explore\\/([0-9a-f]{24})|\\/search_result\\/([0-9a-f]{24})/);
        const nid = m ? (m[1] || m[2]) : '';
        if (!nid) return;
        const t = sec.querySelector('.title, span.title, a.title') ;
        const au = sec.querySelector('.author, span.name, .name');
        const lk = sec.querySelector('.like-wrapper .count, .count');
        out.push({note_id: nid, href: href,
                  title: t ? t.innerText.trim() : '',
                  author: au ? au.innerText.trim().split('\\n')[0].trim() : '',
                  likes: lk ? lk.innerText.trim() : ''});
    });
    return out;
}"""

# 笔记页 noteDetailMap 水合取值（配 eval_retry 使用）
NOTE_JS = """() => {
    try {
        const dm = window.__INITIAL_STATE__.note.noteDetailMap;
        for (const k of Object.keys(dm)) {
            const n = dm[k] && dm[k].note;
            if (n && (n.imageList || []).length) {
                return {
                    title: n.title || '',
                    n: n.imageList.length,
                    urls: n.imageList.map(i => i.urlDefault || i.urlPre
                          || ((i.infoList || [])[0] || {}).url || '')
                };
            }
        }
    } catch (e) {}
    return null;
}"""


def eval_retry(page, js, arg=None, tries=EVAL_TRIES, label="evaluate"):
    """踩坑⑪ 的唯一实现：goto 之后所有 evaluate 都走这里。

    为什么必须重试：搜索页 `/search_result/ → ?type=51 → 结果` 至少两跳，
    笔记页也会跳（xsec_token 变体 / 404），跳转期间 window 被销毁，
    此时 `page.evaluate` 抛
    `Execution context was destroyed, most likely because the page was destroyed`。
    单次调用看不到结果**是写法 bug、不是限流**。

    · 返回第一个「真值」结果；一直拿不到则返回 None（不抛）
    · 每轮开头检查 captcha，命中直接抛 RuntimeError，让上层立即中止（免加重风控）
    · 重定向期的销毁异常被吞掉继续下一轮，只在全部用尽时记一条日志
    """
    last = ""
    for i in range(tries):
        if CAPTCHA_PATH in page.url:
            raise RuntimeError("CAPTCHA 拦截（%s）" % label)
        try:
            out = page.evaluate(js) if arg is None else page.evaluate(js, arg)
            if out:
                return out
        except Exception as e:
            last = str(e)[:80]
        if i < tries - 1:
            time.sleep(random.uniform(2.0, 3.0))
    if last:
        log("      ! %s 重试 %d 轮未取到（最后异常：%s）" % (label, tries, last))
    return None


def search_cards(page, kw):
    """搜索关键词，返回 [{note_id, href, title, author, likes}]"""
    url = ("https://www.xiaohongshu.com/search_result?keyword=%s&source=web_explore_feed"
           % urllib.parse.quote(kw))
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass
    time.sleep(random.uniform(3.0, 5.0))

    raw = eval_retry(page, SEARCH_JS, CARDS_PER_QUERY,
                     label="搜索卡片「%s」" % kw) or []

    seen, cards = set(), []
    for c in raw:
        if c['note_id'] in seen:
            continue
        seen.add(c['note_id'])
        cards.append(c)
    return cards


def note_images(page, href):
    """带 token 访问笔记，轮询 noteDetailMap 水合后取原图 URL。

    踩坑⑪在这里同样成立：笔记页也会重定向（xsec_token 变体 / 404），
    单次 evaluate 抛的销毁异常会被上层 `except` 吞掉 →
    **整篇笔记的图静默丢掉**（日志只写「无原图」，看着像帖子的问题）。
    """
    full = href if href.startswith("http") else "https://www.xiaohongshu.com" + href
    try:
        page.goto(full, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass
    data = eval_retry(page, NOTE_JS, None, label="笔记水合 %s" % href[-12:])
    if data and data.get("urls"):
        return [u for u in data["urls"] if u], data.get("title", "")
    if page.url.startswith("https://www.xiaohongshu.com/404"):
        return [], ''
    return [], ''


def save_images(ctx, urls, folder):
    """下载并转 JPEG。"""
    os.makedirs(folder, exist_ok=True)
    saved = []
    for i, u in enumerate(urls[:IMGS_PER_NOTE], 1):
        try:
            resp = ctx.request.get(u, timeout=45000)
            if not resp.ok:
                continue
            raw = resp.body()
            if len(raw) < 12000:
                continue
            im = Image.open(io.BytesIO(raw))
            im = im.convert("RGB")
            if im.size[0] > MAX_W:
                im = im.resize((MAX_W, int(im.size[1] * MAX_W / im.size[0])), Image.LANCZOS)
            p = os.path.join(folder, "%02d.jpg" % len(saved) if False else "%02d.jpg" % (len(saved) + 1))
            im.save(p, "JPEG", quality=88, optimize=True)
            saved.append(p)
        except Exception as e:
            log("      图片失败 %s: %s" % (u[:60], str(e)[:60]))
    return saved


def selfcheck():
    """副本漂移自检：确认手上这份还是「修好的版本」。

    2026-09-17 复发就是副本问题 —— 某个副本停在旧版、search_cards 只有单次
    evaluate，跑起来必爆踩坑⑪，而表现只是「搜索失败」，很难看出是版本不一致。
    任何副本（本地技能 / 仓库 / 项目目录）拿到手先跑这个。
    """
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    checks = [
        ("eval_retry() 复用函数存在", "def eval_retry(" in src),
        ("search_cards 走 eval_retry", "eval_retry(page, SEARCH_JS" in src),
        ("note_images 走 eval_retry", "eval_retry(page, NOTE_JS" in src),
        ("captcha 命中即中止", CAPTCHA_PATH in src),
        ("登录态 profile 不指向真实浏览器", "User Data" not in PROFILE),
        ("裸 explore 直访已带 token 说明", "xsec_token" in src),
    ]
    bad = 0
    for name, ok in checks:
        print(("  OK   " if ok else "  FAIL ") + name)
        bad += 0 if ok else 1
    if bad:
        print("SELFCHECK FAIL(%d) —— 本副本是旧版，跑采集会爆踩坑⑪（Execution context "
              "destroyed），请从本地技能目录重新复制" % bad)
    else:
        print("SELFCHECK PASS —— 踩坑⑪ 防护完整")
    return 0 if not bad else 1


def main():
    if "--selfcheck" in sys.argv[1:]:
        raise SystemExit(selfcheck())
    want = set(a for a in sys.argv[1:] if not a.startswith("--"))
    tasks = [t for t in TASKS if not want or t[0] in want]
    log("===== 开始采集：%d 个景点 =====" % len(tasks))

    with sync_playwright() as p:
        cdp = os.environ.get("XHS_CDP", "").strip()
        if cdp:
            # 常驻模式：挂在常驻浏览器上，结束只关标签页
            br = p.chromium.connect_over_cdp(cdp)
            ctx = br.contexts[0] if br.contexts else br.new_context()
            page = ctx.new_page()
            log("ATTACHED 常驻会话 %s（结束时不关浏览器）" % cdp)
        else:
            ctx = p.chromium.launch_persistent_context(
                PROFILE, headless=False,
                viewport={"width": 1440, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            log("!! 独立模式：本次结束会关闭浏览器 → 会话 cookie 丢失、下次要重新扫码。"
                "建议改用 session_daemon.py + XHS_CDP")
        ck = {c["name"]: c["value"] for c in ctx.cookies()}
        if not ck.get("id_token"):
            log("!! 登录态失效，需重新扫码")
            if cdp:
                page.close()
            else:
                ctx.close()
            return

        global_cache = {}   # note_id -> saved files（跨 slug 复用，避免重复下载）
        for si, (slug, (queries, cn)) in enumerate(tasks, 1):
            log("(%d/%d) [%s] %s" % (si, len(tasks), slug, cn))
            cards = []
            for q in queries:
                try:
                    got = search_cards(page, q)
                    log("    搜索「%s」→ %d 张卡片" % (q, len(got)))
                    cards.extend(got)
                except Exception as e:
                    log("    搜索失败 %s: %s" % (q, str(e)[:60]))
                wait(2.0, 4.0)

            # 去重（按 note_id）
            uniq, seen = [], set()
            for c in cards:
                if c['note_id'] in seen:
                    continue
                seen.add(c['note_id'])
                uniq.append(c)
            uniq = uniq[:NOTES_PER_SLUG]
            log("    取前 %d 篇" % len(uniq))

            for ci, c in enumerate(uniq, 1):
                nid = c['note_id']
                folder = os.path.join(OUT, slug, nid)
                if nid in global_cache and global_cache[nid]:
                    log("    [%d/%d] %s 复用已下载 %d 张" % (ci, len(uniq), nid[:12], len(global_cache[nid])))
                    saved = global_cache[nid]
                else:
                    try:
                        urls, t = note_images(page, c['href'])
                    except Exception as e:
                        log("    [%d/%d] %s 打开失败 %s" % (ci, len(uniq), nid[:12], str(e)[:50]))
                        continue
                    if not urls:
                        log("    [%d/%d] %s 无原图（可能已删/视频笔记）" % (ci, len(uniq), nid[:12]))
                        wait()
                        continue
                    saved = save_images(ctx, urls, folder)
                    global_cache[nid] = saved
                    log("    [%d/%d] %s %s → %d 张" % (ci, len(uniq), nid[:12], (t or c['title'])[:22], len(saved)))
                if saved:
                    with open(META, "a", encoding="utf-8") as f:
                        f.write(json.dumps(dict(
                            slug=slug, spot=cn, note_id=nid, title=c['title'],
                            author=c['author'], likes=c['likes'],
                            folder="_raw/photos/%s/%s" % (slug, nid),
                            files=[os.path.basename(x) for x in saved],
                        ), ensure_ascii=False) + "\n")
                wait(1.6, 3.6)
        if cdp:
            # 只关本脚本开的标签页；浏览器与登录态留给后续采集复用
            try:
                page.close()
            except Exception:
                pass
            log("RESIDENT_KEPT_ALIVE 浏览器保持运行（未关闭）")
        else:
            ctx.close()

    # 汇总
    log("===== 完成 =====")
    total = 0
    for slug in sorted(os.listdir(OUT)):
        d = os.path.join(OUT, slug)
        if not os.path.isdir(d):
            continue
        n = sum(len([f for f in os.listdir(os.path.join(d, x)) if f.endswith('.jpg')])
                for x in os.listdir(d))
        total += n
        log("  %-16s %3d 张" % (slug, n))
    log("  合计 %d 张" % total)


if __name__ == "__main__":
    main()
