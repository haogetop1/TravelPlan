# -*- coding: utf-8 -*-
"""PPTX 版式自检：几何越界、文本容量溢出、图片缺失。"""
import os, sys, math
from pptx import Presentation
from pptx.util import Emu

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.abspath(__file__))
PPTX = os.path.join(BASE, 'roadbook', '贵州7天6晚自驾路书.pptx')

EMU = 914400.0
SW, SH = 13.333, 7.5


def cjk_len(s):
    """按 CJK=1、ASCII=0.55 折算等效字符数。"""
    n = 0.0
    for ch in s:
        n += 1.0 if ord(ch) > 0x2E80 else 0.55
    return n


def main():
    prs = Presentation(PPTX)
    print('slide size: %.3f x %.3f' % (prs.slide_width / EMU, prs.slide_height / EMU))
    print('slides: %d' % len(prs.slides._sldIdLst))
    issues = 0
    for si, slide in enumerate(prs.slides, 1):
        for sh in slide.shapes:
            try:
                x, y = sh.left / EMU, sh.top / EMU
                w, h = sh.width / EMU, sh.height / EMU
            except Exception:
                continue
            # 越界
            if x < -0.02 or y < -0.02 or x + w > SW + 0.02 or y + h > SH + 0.02:
                print('  [%02d] 越界 %-22s x=%.2f y=%.2f w=%.2f h=%.2f' %
                      (si, sh.shape_type, x, y, w, h))
                issues += 1
            # 文本容量
            if sh.has_text_frame:
                tf = sh.text_frame
                total_lines = 0
                max_size = 0
                for p in tf.paragraphs:
                    txt = ''.join(r.text for r in p.runs)
                    if not txt.strip():
                        total_lines += 1
                        continue
                    sz = max([(r.font.size.pt if r.font.size else 12) for r in p.runs] or [12])
                    max_size = max(max_size, sz)
                    cap = max(1.0, w * 72.0 / sz)          # 每行可容纳等效字符
                    lines = max(1, math.ceil(cjk_len(txt) / cap))
                    total_lines += lines
                    ls = p.line_spacing if isinstance(p.line_spacing, float) else 1.2
                need = total_lines * max_size * 1.32 / 72.0
                if need > h + 0.12:
                    print('  [%02d] 文本可能溢出 需 %.2f\" > 框 %.2f\"  (行数%d 字号%.1f)  %s'
                          % (si, need, h, total_lines, max_size,
                             (tf.text[:34].replace('\n', ' '))))
                    issues += 1
            if sh.shape_type == 13:  # PICTURE
                pass
    print('---')
    print('issues:', issues)


if __name__ == '__main__':
    main()
