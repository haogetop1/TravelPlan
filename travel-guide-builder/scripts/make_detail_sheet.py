# -*- coding: utf-8 -*-
"""把详细版 PPT 的 45 帧拼成带标签的验收联络表 + 一张「交通节点降级」对照图。

产出：
  roadbook/_raw/detail/review/sheet_all.jpg          —— 45 页总览（带页名）
  roadbook/_raw/detail/review/sheet_transit_fix.jpg  —— 含 🚉 交通节点的当日备注页
"""
import os, sys, json, re
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'roadbook', '_raw', 'detail')
OUT = os.path.join(RAW, 'review')
os.makedirs(OUT, exist_ok=True)
DETAIL = os.path.join(RAW, 'detail.html')


def font(sz):
    for p in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf'):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


# ── 1. 取每页标签（用浏览器读 DOM，避免嵌套 div 的正则地狱）──
with sync_playwright() as p:
    b = p.chromium.launch(args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 1920, 'height': 1080})
    pg.goto('file:///' + DETAIL.replace('\\', '/'))
    pg.wait_for_timeout(2000)
    labels = pg.evaluate("""() => {
        const pick = s => {
            for (const sel of ['.slide-t', '.st-title', 'h1', 'h2', '.card-h', '.mini']) {
                const e = s.querySelector(sel);
                if (e && e.innerText.trim()) return e.innerText.trim().replace(/\\s+/g, ' ');
            }
            return (s.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 26);
        };
        return [...document.querySelectorAll('.slide')].map(pick);
    }""")
    # 找出含 🚉 的页序号（1-based）
    transit_pages = pg.evaluate("""() => {
        const out = [];
        document.querySelectorAll('.slide').forEach((s, i) => {
            if (s.innerText && s.innerText.includes('\\uD83D\\uDE89')) out.push(i + 1);
        });
        return out;
    }""")
    b.close()

print('pages =', len(labels))
print('含 🚉 的页 =', transit_pages)
for i, l in enumerate(labels, 1):
    print('  P%02d  %s' % (i, l[:44]))

json.dump({'labels': labels, 'transit_pages': transit_pages},
          open(os.path.join(OUT, 'detail_pages.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=2)

# ── 2. 45 页总览 ──
TW, TH, PAD, LBL = 340, 191, 8, 20
COLS, ROWS = 5, 9
W = COLS * TW + (COLS + 1) * PAD
H = ROWS * (TH + LBL + PAD) + PAD
cv = Image.new('RGB', (W, H), (58, 58, 58))
d = ImageDraw.Draw(cv)
f = font(15)
files = sorted(x for x in os.listdir(RAW) if re.fullmatch(r'd_\d+\.png', x))
print('frames =', len(files))
for i, fn in enumerate(files):
    r, c = divmod(i, COLS)
    x = PAD + c * (TW + PAD)
    y = PAD + r * (TH + LBL + PAD)
    tag = 'P%02d' % (i + 1)
    lb = labels[i] if i < len(labels) else ''
    hl = (176, 137, 104) if (i + 1) in transit_pages else (86, 86, 86)
    d.rectangle([x, y, x + TW, y + LBL], fill=hl)
    d.text((x + 6, y + 2), '%s  %s' % (tag, lb[:22]), font=f, fill=(255, 255, 255))
    im = Image.open(os.path.join(RAW, fn)).convert('RGB').resize((TW, TH), Image.LANCZOS)
    cv.paste(im, (x, y + LBL))
cv.save(os.path.join(OUT, 'sheet_all.jpg'), quality=88)
print('WROTE sheet_all.jpg', cv.size)

# ── 3. 🚉 页对照（放大）──
if transit_pages:
    TW2, TH2, PAD2, LBL2 = 900, 506, 12, 26
    W2 = TW2 + PAD2 * 2
    H2 = PAD2 + len(transit_pages) * (TH2 + LBL2 + PAD2)
    cv2 = Image.new('RGB', (W2, H2), (58, 58, 58))
    d2 = ImageDraw.Draw(cv2)
    f2 = font(18)
    y = PAD2
    for pno in transit_pages:
        fn = os.path.join(RAW, 'd_%02d.png' % pno)
        if not os.path.exists(fn):
            continue
        lb = labels[pno - 1] if pno - 1 < len(labels) else ''
        d2.rectangle([PAD2, y, PAD2 + TW2, y + LBL2], fill=(176, 137, 104))
        d2.text((PAD2 + 8, y + 3), 'P%02d  %s   ← 含 🚉 交通节点' % (pno, lb[:56]),
                font=f2, fill=(255, 255, 255))
        im = Image.open(fn).convert('RGB').resize((TW2, TH2), Image.LANCZOS)
        cv2.paste(im, (PAD2, y + LBL2))
        y += TH2 + LBL2 + PAD2
    cv2.save(os.path.join(OUT, 'sheet_transit_fix.jpg'), quality=90)
    print('WROTE sheet_transit_fix.jpg', cv2.size)
