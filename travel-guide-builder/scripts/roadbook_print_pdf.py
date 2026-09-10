# -*- coding: utf-8 -*-
"""把路书 HTML 打印为 PDF（与 HTML 版式完全一致）。"""
import os, sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.abspath(__file__))
HTML = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, 'roadbook', '贵州7天6晚自驾路书.html')
PDF = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, 'roadbook', '贵州7天6晚自驾路书.pdf')

with sync_playwright() as p:
    b = p.chromium.launch(args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 760, 'height': 1100})
    pg.goto('file:///' + os.path.abspath(HTML).replace('\\', '/'))
    pg.wait_for_timeout(2500)
    pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    pg.wait_for_timeout(2000)
    pg.evaluate("window.scrollTo(0, 0)")
    pg.wait_for_timeout(800)
    pg.emulate_media(media='print')
    pg.pdf(path=PDF, format='A4', print_background=True,
           margin={'top': '10mm', 'bottom': '10mm', 'left': '8mm', 'right': '8mm'},
           prefer_css_page_size=False)
    b.close()
print('written', PDF, os.path.getsize(PDF) // 1024, 'KB')
