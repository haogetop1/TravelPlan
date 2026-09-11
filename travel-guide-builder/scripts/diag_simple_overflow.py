# -*- coding: utf-8 -*-
"""诊断方案二逐日页的溢出：逐页列出每张卡片的自然高度 / 可视高度 / 超出量。"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
FITTED = os.environ.get("DIAG_HTML") or os.path.join(
    BASE, "roadbook", "_raw", "detail", "simple_fitted.html")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

JS = """() => {
  const out = [];
  document.querySelectorAll('.slide').forEach((s, i) => {
    const sr = s.getBoundingClientRect();
    const sb = sr.bottom;
    const cards = [];
    s.querySelectorAll('.card, .figmap, .pf-col').forEach(c => {
      const hd = c.querySelector(':scope > .card-h');
      const b  = c.querySelector(':scope > .card-b');
      let rec = {
        head: hd ? hd.innerText.trim().slice(0, 16) : '',
        cardH: Math.round(c.getBoundingClientRect().height),
        cardOver: Math.round(c.getBoundingClientRect().bottom - sb)
      };
      if (b) {
        rec.bodyClient = b.clientHeight;
        rec.bodyScroll = b.scrollHeight;
        rec.clip = Math.max(0, b.scrollHeight - b.clientHeight);
        rec.fs = getComputedStyle(b).fontSize;
        // 真实内容高度：最后一个子元素底边 - 内容盒顶边 + 下内边距
        const kids = b.children;
        if (kids.length) {
          const cs = getComputedStyle(b);
          const top = b.getBoundingClientRect().top + parseFloat(cs.paddingTop);
          const last = kids[kids.length - 1].getBoundingClientRect().bottom;
          rec.contentH = Math.round(last - top + parseFloat(cs.paddingBottom));
        } else {
          rec.contentH = 0;
        }
      }
      cards.push(rec);
    });
    const col = s.querySelector('.col-r, .pf, .dgrid, .dstack, .sstack, .stop');
    out.push({
      page: i + 1,
      colScroll: col ? col.scrollHeight : null,
      colClient: col ? col.clientHeight : null,
      colClip: col ? Math.max(0, col.scrollHeight - col.clientHeight) : 0,
      cards: cards
    });
  });
  return out;
}"""

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    pg.goto("file:///" + FITTED.replace("\\", "/"), wait_until="load")
    pg.wait_for_timeout(1200)
    data = pg.evaluate(JS)
    br.close()

bad = 0
DAYPAGES = range(5, 19)      # 方案二逐日页（19 物品清单 / 20 结束页 不算）
for d in data:
    clip = d["colClip"] or 0
    card_over = max([c["cardOver"] for c in d["cards"]] or [0])
    card_clip = max([c.get("clip", 0) for c in d["cards"]] or [0])
    is_day = d["page"] in DAYPAGES
    if not is_day and clip <= 4 and card_over <= 4 and card_clip <= 4:
        continue
    if clip > 4 or card_over > 4 or card_clip > 4:
        bad += 1
    print("=" * 78)
    print("P%02d  容器 clip=%dpx (scroll=%s / client=%s)  最大卡底超出=%dpx  最大内部裁剪=%dpx"
          % (d["page"], clip, d["colScroll"], d["colClient"], card_over, card_clip))
    for c in d["cards"]:
        inner = c.get("contentH")
        flag = []
        if c["cardOver"] > 4:
            flag.append("卡底超出 %dpx" % c["cardOver"])
        if c.get("clip", 0) > 4:
            flag.append("内部裁剪 %dpx" % c["clip"])
        print("     %-16s 卡高%4dpx  body %s/%s  内容%4s  字号%-6s  %s"
              % (c["head"], c["cardH"],
                 c.get("bodyClient"), c.get("bodyScroll"),
                 ("%d" % inner) if inner is not None else "-",
                 c.get("fs", ""),
                 ("← " + " / ".join(flag)) if flag else ""))
print()
print("有溢出的页数 =", bad, "/", len(data))
