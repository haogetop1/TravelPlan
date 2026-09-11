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
"""
import os, sys, json, time, random, io, re, urllib.parse

sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.dirname(os.path.abspath(__file__))


def _find_profile():
    """定位小红书登录态 profile。

    优先级：环境变量 XHS_PROFILE → 从当前目录向上找 <workspace>/.workbuddy/xhs_qr_profile
    → 兜底 ~/.workbuddy/xhs_qr_profile。
    不要写死绝对路径——那既会在别人机器上直接失效，也会把本机用户名泄进公开仓库。
    """
    env = os.environ.get("XHS_PROFILE")
    if env:
        return env
    cur = os.path.abspath(os.getcwd())
    while True:
        cand = os.path.join(cur, ".workbuddy", "xhs_qr_profile")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.join(os.path.expanduser("~"), ".workbuddy", "xhs_qr_profile")


PROFILE = _find_profile()
OUT = os.path.join(BASE, "roadbook", "_raw", "photos")
LOG = os.path.join(BASE, "roadbook", "_raw", "_photos.log")
META = os.path.join(BASE, "roadbook", "_raw", "_photos.jsonl")
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


def search_cards(page, kw):
    """搜索关键词，返回 [{note_id, href, title, author, likes}]"""
    url = ("https://www.xiaohongshu.com/search_result?keyword=%s&source=web_explore_feed"
           % urllib.parse.quote(kw))
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(random.uniform(4.0, 6.0))
    raw = page.evaluate("""(lim) => {
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
    }""", CARDS_PER_QUERY)
    # 去重
    seen, cards = set(), []
    for c in raw:
        if c['note_id'] in seen:
            continue
        seen.add(c['note_id'])
        cards.append(c)
    return cards


def note_images(page, href):
    """带 token 访问笔记，轮询 noteDetailMap 水合后取原图 URL。"""
    full = href if href.startswith("http") else "https://www.xiaohongshu.com" + href
    page.goto(full, wait_until="domcontentloaded", timeout=60000)
    urls = []
    for _ in range(12):
        time.sleep(1.4)
        data = page.evaluate("""() => {
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
        }""")
        if data and data.get('urls'):
            urls = [u for u in data['urls'] if u]
            return urls, data.get('title', '')
        if page.url.startswith("https://www.xiaohongshu.com/404"):
            return [], ''
    return urls, ''


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


def main():
    want = set(sys.argv[1:])
    tasks = [t for t in TASKS if not want or t[0] in want]
    log("===== 开始采集：%d 个景点 =====" % len(tasks))

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ck = {c["name"]: c["value"] for c in ctx.cookies()}
        if not ck.get("id_token"):
            log("!! 登录态失效，需重新扫码")
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
