# -*- coding: utf-8 -*-
"""把 HTML 用移动端视口截图（分段），用于目视验收排版。

用法： python shot.py <html路径> [段数]
"""
import os, sys, math
from PIL import Image
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'roadbook', '_raw', 'shots')
os.makedirs(OUT, exist_ok=True)

args = [a for a in sys.argv[1:] if not a.startswith('-')]
HTML = args[0] if args else os.path.join(BASE, 'roadbook', '贵州7天6晚自驾路书.html')
SEGS = int(args[1]) if len(args) > 1 else 6
W = 430

with sync_playwright() as p:
    b = p.chromium.launch(args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': W, 'height': 900}, device_scale_factor=2)
    pg.goto('file:///' + os.path.abspath(HTML).replace('\\', '/'))
    pg.wait_for_timeout(2500)
    # 触发懒加载
    pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    pg.wait_for_timeout(1500)
    pg.evaluate("window.scrollTo(0, 0)")
    pg.wait_for_timeout(800)
    h = pg.evaluate("document.body.scrollHeight")
    print('page height:', h)
    full = os.path.join(OUT, '_full.png')
    pg.screenshot(path=full, full_page=True)
    b.close()

im = Image.open(full)
print('full size:', im.size)
seg_h = math.ceil(im.size[1] / SEGS)
paths = []
for i in range(SEGS):
    top = i * seg_h
    bot = min(im.size[1], top + seg_h)
    if top >= im.size[1]:
        break
    seg = im.crop((0, top, im.size[0], bot))
    # 压到可读尺寸
    if seg.size[0] > 700:
        r = 700 / seg.size[0]
        seg = seg.resize((700, int(seg.size[1] * r)), Image.LANCZOS)
    pth = os.path.join(OUT, 'seg_%02d.jpg' % (i + 1))
    seg.convert('RGB').save(pth, quality=84, optimize=True)
    paths.append(pth)
    print('  ', pth, seg.size)
