# -*- coding: utf-8 -*-
"""把 HTML 用移动端视口截图（分段），用于目视验收排版。

用法：
  python html_screenshot.py <html路径> [段数] [--out 输出目录]

输出目录默认取「HTML 同级目录 / _raw/shots」（路书工程约定），
不再往技能目录里写产物（技能目录应保持只读）；也可用 --out 显式指定。
"""
import os, sys, math
from PIL import Image
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

argv = sys.argv[1:]
out_arg = None
if '--out' in argv:                 # 先摘掉 --out 及其值，免得被当成位置参数
    i = argv.index('--out')
    out_arg = argv[i + 1] if i + 1 < len(argv) else None
    del argv[i:i + 2]
args = [a for a in argv if not a.startswith('-')]

if not args:
    print(__doc__)
    sys.exit(1)

HTML = os.path.abspath(args[0])
SEGS = int(args[1]) if len(args) > 1 else 6
W = 430

OUT = out_arg or os.path.join(os.path.dirname(HTML), '_raw', 'shots')
os.makedirs(OUT, exist_ok=True)

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
