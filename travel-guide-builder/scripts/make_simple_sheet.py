# -*- coding: utf-8 -*-
"""方案二（简洁版）验收图。

产出：
  roadbook/_raw/detail/review/sheet_simple_all.jpg   —— 20 页总览（带页名）
  roadbook/_raw/detail/review/sheet_simple_day1.jpg  —— DAY1 两页放大（行程 + 吃住）
"""
import os
import re
import sys
import json

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "roadbook", "_raw", "detail")
OUT = os.path.join(RAW, "review")
os.makedirs(OUT, exist_ok=True)
HTML = os.path.join(RAW, "simple_fitted.html")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def font(sz):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


# ── 1. 用浏览器读每页标题（避免嵌套 div 的正则地狱）──
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto("file:///" + HTML.replace("\\", "/"))
    pg.wait_for_timeout(1500)
    labels = pg.evaluate("""() => {
        const pick = s => {
            for (const sel of ['.hd-t', 'h1', '.cover-kicker', '.end-title']) {
                const e = s.querySelector(sel);
                if (e && e.innerText.trim()) return e.innerText.trim().replace(/\\s+/g, ' ');
            }
            return (s.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 24);
        };
        return [...document.querySelectorAll('.slide')].map(pick);
    }""")
    br.close()

print("pages =", len(labels))
for i, l in enumerate(labels, 1):
    print("  P%02d  %s" % (i, l[:46]))
json.dump({"labels": labels},
          open(os.path.join(OUT, "simple_pages.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# ── 2. 20 页总览（5 列 × 4 行）──
files = sorted(x for x in os.listdir(RAW) if re.fullmatch(r"c_\d+\.png", x))
print("frames =", len(files))
TW, TH, PAD, LBL = 340, 191, 8, 20
COLS = 5
ROWS = (len(files) + COLS - 1) // COLS
W = COLS * TW + (COLS + 1) * PAD
H = ROWS * (TH + LBL + PAD) + PAD
cv = Image.new("RGB", (W, H), (58, 58, 58))
d = ImageDraw.Draw(cv)
f = font(15)
for i, fn in enumerate(files):
    r, c = divmod(i, COLS)
    x = PAD + c * (TW + PAD)
    y = PAD + r * (TH + LBL + PAD)
    lb = labels[i] if i < len(labels) else ""
    # 逐日页交替底色，方便一眼看出「每天两页」的节奏
    hl = (176, 137, 104) if i in range(4, 18) else (86, 86, 86)
    if i in range(4, 18) and (i - 4) % 2:
        hl = (140, 108, 82)
    d.rectangle([x, y, x + TW, y + LBL], fill=hl)
    d.text((x + 6, y + 2), "P%02d  %s" % (i + 1, lb[:22]), font=f, fill=(255, 255, 255))
    im = Image.open(os.path.join(RAW, fn)).convert("RGB").resize((TW, TH), Image.LANCZOS)
    cv.paste(im, (x, y + LBL))
cv.save(os.path.join(OUT, "sheet_simple_all.jpg"), quality=88)
print("WROTE sheet_simple_all.jpg", cv.size)

# ── 3. DAY1 两页放大（行程 + 吃住）──
pick = [5, 6]
TW2, TH2, PAD2, LBL2 = 960, 540, 14, 28
W2 = PAD2 * 2 + TW2
H2 = PAD2 + len(pick) * (TH2 + LBL2 + PAD2)
cv2 = Image.new("RGB", (W2, H2), (58, 58, 58))
d2 = ImageDraw.Draw(cv2)
f2 = font(19)
y = PAD2
for pno in pick:
    fn = os.path.join(RAW, "c_%02d.png" % pno)
    if not os.path.exists(fn):
        continue
    lb = labels[pno - 1] if pno - 1 < len(labels) else ""
    d2.rectangle([PAD2, y, PAD2 + TW2, y + LBL2], fill=(176, 137, 104))
    d2.text((PAD2 + 8, y + 4), "P%02d  %s" % (pno, lb[:52]), font=f2, fill=(255, 255, 255))
    im = Image.open(fn).convert("RGB").resize((TW2, TH2), Image.LANCZOS)
    cv2.paste(im, (PAD2, y + LBL2))
    y += TH2 + LBL2 + PAD2
cv2.save(os.path.join(OUT, "sheet_simple_day1.jpg"), quality=90)
print("WROTE sheet_simple_day1.jpg", cv2.size)
