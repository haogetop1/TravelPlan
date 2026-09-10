# -*- coding: utf-8 -*-
"""打印 contact sheet 的 编号 -> 图片路径 + 来源帖子标题 对照表，供精确挑图。"""
import os, sys, json

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, 'roadbook', '_raw', 'photos')
META = os.path.join(BASE, 'roadbook', '_raw', '_photos.jsonl')
COLS = 4

titles = {}
if os.path.exists(META):
    for line in open(META, encoding='utf-8'):
        try:
            r = json.loads(line)
            titles[r['note_id']] = (r.get('title') or '')[:26]
        except Exception:
            pass


def run(slug):
    d = os.path.join(SRC, slug)
    items = []
    for nid in sorted(os.listdir(d)):
        sub = os.path.join(d, nid)
        if not os.path.isdir(sub):
            continue
        for f in sorted(os.listdir(sub)):
            if f.endswith('.jpg'):
                items.append((nid, f))
    print('=' * 66)
    print('%s  (%d 张)' % (slug, len(items)))
    for i, (nid, fn) in enumerate(items):
        print('  %02d  %s/%s  %s' % (i + 1, nid, fn, titles.get(nid, '')))


if __name__ == '__main__':
    for s in sys.argv[1:]:
        run(s)
