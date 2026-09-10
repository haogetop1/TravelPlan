# -*- coding: utf-8 -*-
"""把路书 HTML 打成单文件版（图片 base64 内嵌），便于直接转发分享。"""
import os, re, sys, base64, mimetypes

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.abspath(__file__))
RB = os.path.join(BASE, 'roadbook')
SRC = os.path.join(RB, '贵州7天6晚自驾路书.html')
DST = os.path.join(RB, '贵州7天6晚自驾路书_单文件版.html')

html = open(SRC, encoding='utf-8').read()
refs = sorted(set(re.findall(r'src="(assets/[^"]+)"', html)))
print('引用资源:', len(refs))

total = 0
for rel in refs:
    p = os.path.join(RB, rel.replace('/', os.sep))
    if not os.path.exists(p):
        print('  缺失', rel)
        continue
    ext = os.path.splitext(p)[1].lower()
    mime = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.webp': 'image/webp'}.get(ext, mimetypes.guess_type(p)[0] or 'image/jpeg')
    b = open(p, 'rb').read()
    total += len(b)
    uri = 'data:%s;base64,%s' % (mime, base64.b64encode(b).decode('ascii'))
    html = html.replace('src="%s"' % rel, 'src="%s"' % uri)

open(DST, 'w', encoding='utf-8').write(html)
print('written', DST)
print('内嵌原始体积 %.1f MB -> 文件 %.1f MB' % (total / 1048576, os.path.getsize(DST) / 1048576))
