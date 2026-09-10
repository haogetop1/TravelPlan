# -*- coding: utf-8 -*-
"""候选图放大复核：review.py <slug> <序号,序号,...>  序号来自 list_picks.py"""
import os, sys, math
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, 'roadbook', '_raw', 'photos')
OUT = os.path.join(BASE, 'roadbook', '_raw', 'review')
os.makedirs(OUT, exist_ok=True)

COLS, CELL_W, CELL_H, PAD, LABEL_H = 3, 420, 360, 10, 26
try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 19)
except Exception:
    FONT = ImageFont.load_default()


def all_items(slug):
    d = os.path.join(SRC, slug)
    items = []
    for nid in sorted(os.listdir(d)):
        sub = os.path.join(d, nid)
        if not os.path.isdir(sub):
            continue
        for f in sorted(os.listdir(sub)):
            if f.endswith('.jpg'):
                items.append((nid, f, os.path.join(sub, f)))
    return items


def main():
    slug = sys.argv[1]
    idxs = [int(x) for x in sys.argv[2].replace(' ', '').split(',') if x]
    items = all_items(slug)
    sel = [items[i - 1] for i in idxs if 1 <= i <= len(items)]
    rows = math.ceil(len(sel) / COLS)
    canvas = Image.new('RGB', (COLS * (CELL_W + PAD) + PAD,
                              rows * (CELL_H + LABEL_H + PAD) + PAD), (250, 247, 242))
    dr = ImageDraw.Draw(canvas)
    for i, (nid, fn, p) in enumerate(sel):
        c, r = i % COLS, i // COLS
        x = PAD + c * (CELL_W + PAD)
        y = PAD + r * (CELL_H + LABEL_H + PAD)
        im = Image.open(p).convert('RGB')
        im.thumbnail((CELL_W, CELL_H), Image.LANCZOS)
        canvas.paste(im, (x + (CELL_W - im.size[0]) // 2, y + (CELL_H - im.size[1]) // 2))
        dr.rectangle([x, y, x + CELL_W - 1, y + CELL_H - 1], outline=(205, 195, 180))
        dr.rectangle([x, y, x + 64, y + 24], fill=(176, 137, 104))
        dr.text((x + 9, y + 2), '#%02d' % idxs[i], fill=(255, 255, 255), font=FONT)
        dr.text((x + 2, y + CELL_H + 3), '%s' % nid[:10], fill=(120, 105, 90), font=FONT)
    out = os.path.join(OUT, slug + '_review.jpg')
    canvas.save(out, quality=84, optimize=True)
    print('written', out, canvas.size, 'count', len(sel))


if __name__ == '__main__':
    main()
