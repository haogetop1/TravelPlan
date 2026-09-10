# -*- coding: utf-8 -*-
"""为采集到的原图生成 contact sheet（编号 + 来源帖子），便于逐张挑选。"""
import os, sys, json, math
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, 'roadbook', '_raw', 'photos')
OUT = os.path.join(BASE, 'roadbook', '_raw', 'contact2')
os.makedirs(OUT, exist_ok=True)

COLS, CELL_W, CELL_H, PAD, LABEL_H = 4, 340, 290, 8, 24
try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
except Exception:
    FONT = ImageFont.load_default()


def build(slug):
    d = os.path.join(SRC, slug)
    items = []
    for nid in sorted(os.listdir(d)):
        sub = os.path.join(d, nid)
        if not os.path.isdir(sub):
            continue
        for f in sorted(os.listdir(sub)):
            if f.endswith('.jpg'):
                items.append((nid, f, os.path.join(sub, f)))
    if not items:
        print(slug, 'EMPTY'); return None
    rows = math.ceil(len(items) / COLS)
    canvas = Image.new('RGB', (COLS * (CELL_W + PAD) + PAD, rows * (CELL_H + LABEL_H + PAD) + PAD), (250, 247, 242))
    dr = ImageDraw.Draw(canvas)
    for i, (nid, fn, p) in enumerate(items):
        c, r = i % COLS, i // COLS
        x = PAD + c * (CELL_W + PAD)
        y = PAD + r * (CELL_H + LABEL_H + PAD)
        im = Image.open(p).convert('RGB')
        im.thumbnail((CELL_W, CELL_H), Image.LANCZOS)
        canvas.paste(im, (x + (CELL_W - im.size[0]) // 2, y + (CELL_H - im.size[1]) // 2))
        dr.rectangle([x, y, x + CELL_W - 1, y + CELL_H - 1], outline=(205, 195, 180))
        dr.rectangle([x, y, x + 52, y + 22], fill=(176, 137, 104))
        dr.text((x + 7, y + 1), '%02d' % (i + 1), fill=(255, 255, 255), font=FONT)
        dr.text((x + 2, y + CELL_H + 2), '%s %s' % (nid[:8], fn), fill=(120, 105, 90), font=FONT)
    out = os.path.join(OUT, slug + '.jpg')
    canvas.save(out, quality=80, optimize=True)
    print('%-16s %2d张 -> %s' % (slug, len(items), os.path.basename(out)))
    return out


if __name__ == '__main__':
    slugs = sys.argv[1:] or sorted(os.listdir(SRC))
    for s in slugs:
        build(s)
