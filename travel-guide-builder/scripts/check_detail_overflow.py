# -*- coding: utf-8 -*-
"""详细版 PPT（整页截图型）溢出检测：在 1920×1080 视口下逐页量内容高度。

判据：
  1) 任一 .card-b 的 scrollHeight > clientHeight（内部被裁）
  2) .slide 内最深内容的底边 > slide 可视线（页底）
"""
import os, sys, json
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.abspath(__file__))
DETAIL = os.path.join(BASE, 'roadbook', '_raw', 'detail', 'detail.html')
# 优先量「自动缩排后」的快照 —— 那才是真正被截成 PPT 的那一版
FITTED = os.path.join(BASE, 'roadbook', '_raw', 'detail', 'detail_fitted.html')
OUT = os.path.join(BASE, 'roadbook', '_raw', 'detail', 'review', 'overflow.json')

with sync_playwright() as p:
    b = p.chromium.launch(args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 1920, 'height': 1080}, device_scale_factor=1)
    target = FITTED if os.path.exists(FITTED) else DETAIL
    print('量测对象:', os.path.basename(target))
    pg.goto('file:///' + target.replace('\\', '/'))
    pg.wait_for_timeout(2500)
    res = pg.evaluate("""() => {
        const out = [];
        document.querySelectorAll('.slide').forEach((s, i) => {
            const sr = s.getBoundingClientRect();
            let inner = [];
            s.querySelectorAll('.card-b').forEach(c => {
                const over = c.scrollHeight - c.clientHeight;
                if (over > 1) inner.push({cls: 'card-b', over,
                    head: (c.closest('.card')?.querySelector('.card-h')?.innerText || '').trim().slice(0, 20)});
            });
            // 最深内容底边
            let maxBottom = 0, who = '';
            s.querySelectorAll('*').forEach(e => {
                const r = e.getBoundingClientRect();
                if (r.height > 0 && r.bottom > maxBottom) { maxBottom = r.bottom; who = e.className || e.tagName; }
            });
            const spill = Math.round(maxBottom - (sr.bottom - 4));
            out.push({p: i + 1, h: Math.round(sr.height), inner, spill,
                      who: String(who).slice(0, 26)});
        });
        return out;
    }""")
    b.close()

bad_inner = [x for x in res if x['inner']]
bad_spill = [x for x in res if x['spill'] > 0]
print('pages =', len(res))
print('--- .card-b 内部被裁 ---')
for x in bad_inner:
    for it in x['inner']:
        print('  P%02d  %s 溢出 %dpx  [%s]' % (x['p'], it['cls'], it['over'], it['head']))
if not bad_inner:
    print('  无')
print('--- 页面底部溢出（内容超出 1080px）---')
for x in bad_spill:
    print('  P%02d  超出 %dpx  (最深元素 %s)' % (x['p'], x['spill'], x['who']))
if not bad_spill:
    print('  无')
json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('WROTE', OUT)
