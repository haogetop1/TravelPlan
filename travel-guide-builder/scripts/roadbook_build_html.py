# -*- coding: utf-8 -*-
"""生成图文路书 HTML。

用法：
  python build_html.py            # 阶段1：封面 + 总篇章 + DAY1
  python build_html.py --stage 7  # 全量 7 天
"""
import os, re, sys, json, html, shutil, argparse
from PIL import Image
from jinja2 import Environment, FileSystemLoader

sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.dirname(os.path.abspath(__file__))
RB = os.path.join(BASE, 'roadbook')
PHOTO_SRC = os.path.join(RB, '_raw', 'photos')
IMG_OUT = os.path.join(RB, 'assets', 'img')
MAPS = os.path.join(RB, 'assets', 'maps')
TPL = os.path.join(RB, 'templates')

# ============ 挑图（编号见 list_picks.py 输出，已逐张目视复核） ============
PICKS = {
    "qianlingshan": [
        (1,  "黔灵山公园 · 入园步道"),
        (10, "猕猴抢食特写"),
        (12, "猕猴蹲坐树桩"),
        (19, "弘福寺石刻牌坊"),
        (36, "弘福寺山门"),
        (27, "登顶远眺贵阳城区"),
    ],
    "qingyunshiji": [
        (17, "「贵阳」红色大字打卡墙"),
        (19, "「贵阳」蓝色大字墙"),
        (21, "「贵州」大字墙"),
        (27, "青云市集打卡装置"),
        (36, "市集彩色几何建筑"),
        (40, "市集店铺与招牌"),
    ],
}

# 封面主视觉（配图完成后填入 slug + 序号）
HERO = ("huangguoshu", 9)

PHOTO_MAX_W = 1200
PHOTO_Q = 82


def norm_name(s):
    return re.sub(r'[^\w\u4e00-\u9fa5]', '', s or '')


def esc(t):
    return html.escape(t or '')


def rich(t):
    """正文渲染：转义 + 【】加粗 + 换行保留。"""
    t = esc(t)
    t = re.sub(r'【([^】]{1,24})】', r'<b>【\1】</b>', t)
    return t


def load_meta():
    meta = {}
    p = os.path.join(RB, '_raw', '_photos.jsonl')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            try:
                r = json.loads(line)
                meta.setdefault(r['note_id'], r)
            except Exception:
                pass
    return meta


def all_photos(slug):
    d = os.path.join(PHOTO_SRC, slug)
    items = []
    if not os.path.isdir(d):
        return items
    for nid in sorted(os.listdir(d)):
        sub = os.path.join(d, nid)
        if not os.path.isdir(sub):
            continue
        for f in sorted(os.listdir(sub)):
            if f.endswith('.jpg'):
                items.append((nid, f, os.path.join(sub, f)))
    return items


def build_asset(slug, nid, fn, src):
    """压缩并复制到 assets/img/<slug>/，返回相对路径。"""
    out_dir = os.path.join(IMG_OUT, slug)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, '%s_%s' % (nid[:8], fn))
    if not os.path.exists(out):
        im = Image.open(src).convert('RGB')
        if im.size[0] > PHOTO_MAX_W:
            im = im.resize((PHOTO_MAX_W, int(im.size[1] * PHOTO_MAX_W / im.size[0])), Image.LANCZOS)
        im.save(out, 'JPEG', quality=PHOTO_Q, optimize=True)
    return 'assets/img/%s/%s' % (slug, os.path.basename(out))


def resolve_photos(slug, meta):
    """按 PICKS 顺序产出照片列表。"""
    if not slug or slug not in PICKS:
        return []
    items = all_photos(slug)
    out = []
    for idx, cap in PICKS[slug]:
        if not (1 <= idx <= len(items)):
            continue
        nid, fn, src = items[idx - 1]
        rel = build_asset(slug, nid, fn, src)
        m = meta.get(nid, {})
        au = (m.get('author') or '').strip()
        credit = ('📷 小红书 @%s · %s' % (au, nid[:8])) if au else ('📷 小红书 · %s' % nid[:8])
        out.append(dict(src=rel, caption=cap, credit=credit))
    return out


# ============ 出发前必看 ============
ESSENTIALS = dict(
    tickets=[
        "黄果树「水帘洞」需提前 5-7 天在「一码游贵州」或安旅通预约，国庆现场基本买不到",
        "荔波小七孔提前在「云游荔波」小程序分时段购票，研究生凭学生证免门票",
        "西江千户苗寨建议提前 2-4 周订房 + 官方渠道购票，国庆限流",
        "黔灵山公园免费，但需在「一码游贵州」提前预约（限流）",
        "青岩古镇主街门票 ¥10，另 4 个联票景点 ¥60 不推荐买",
    ],
    driving=[
        "国庆 10/1 00:00 - 10/7 24:00 全国高速免费，过路费按 ¥0 计",
        "主要车程：贵阳→黄果树 2h、黄果树→荔波 3h、荔波→西江 4h、西江→贵阳 3h",
        "贵州山路区间测速密集，务必按限速行驶；车机提前下载离线地图（山区信号差）",
        "取车时绕车录像 + 拍照留证，核验油量、车灯、备胎，问清保险覆盖范围",
        "还车前加满油并再次环车录像，保留加油小票与租车凭证",
    ],
    hotel=[
        "2 人共用 1 间经济型双人标间，国庆房价普遍翻倍，越晚越贵",
        "西江订「大北门 / 西门」附近，避免拖着行李爬山进寨",
        "荔波住小七孔东门附近，次日 9 点入园可避开 70% 人流",
        "贵阳住喷水池 / 大十字商圈，步行可达小吃街 + 地铁，方便次日出发",
    ],
)


def clean_line(s):
    return re.sub(r'^[→\-\s]+', '', (s or '').strip())


def build_view(content, stage, meta):
    m = content['meta']
    all_days = []
    for d in content['days']:
        chain = [clean_line(x) for x in d['brief'] if clean_line(x)]
        chain_html = ' <span class="arw">→</span> '.join(esc(x) for x in chain)
        trans = esc(d.get('transport_raw') or '')
        trans_html = trans.replace('→', '<span class="arw">→</span>')

        secs = []
        ordn = 0
        for s in d['sections']:
            nm = s['name']
            kind = 'spot'
            if any(k in nm for k in ('机场', '登机', '还车')):
                kind = 'airport'
            elif any(k in nm for k in ('市区', '县城', '采购', '步行街', '小镇')):
                kind = 'city'
            if kind == 'spot':
                ordn += 1
            photos = resolve_photos(s.get('slug'), meta)
            n = len(photos)
            cols = 2 if n in (2, 4) else 3
            secs.append(dict(
                name=nm, short=s['short'], kind=kind, ord=ordn,
                map=s.get('map'), detail_html=rich(s.get('detail')),
                photos=photos, photo_cols=cols,
                shots=[b for b in s.get('shots', []) if b.get('lines')],
                tips=[t for t in (s.get('tips') or []) if t],
                notice=[t for t in (s.get('notice') or []) if t],
            ))

        all_days.append(dict(
            day=d['day'], date=d['date'], weekday=d['weekday'],
            from_city=d['from_city'],
            to_display=d.get('to_city') or d.get('city') or '',
            transport_html=trans_html, chain_html=chain_html,
            stay_note=(d.get('stay_note') or '').replace('住宿城市：', '').strip(),
            city_display=d.get('city', ''), city_map=d.get('city_map'),
            food=[clean_line(x) for x in d.get('food', [])],
            hotel=[clean_line(x) for x in d.get('hotel', [])
                   if '最终住宿后续' not in x],
            sections=secs, day_shots=d.get('day_shots', []),
            day_tips=d.get('day_tips', []), day_notice=d.get('day_notice', []),
            night=d.get('to_city') or d.get('city') or '',
        ))

    b = content['budget']
    budget = dict(
        headers=b['headers'], rows=b['rows'],
        per_weekday=b['per_weekday'], per_holiday=b['per_holiday'],
        total_weekday=b['total_weekday'], total_holiday=b['total_holiday'],
        delta_note="平日与国庆的差距主要是<b>机票 2.8× 与住宿 2.0×</b>，合计人均多花 ¥2,827。"
                   "好消息是国庆高速免费，过路费归零，油路费反而比平日便宜 ¥175/人。"
                   "建议：<b>机票与西江住宿尽早锁定</b>，这两项是涨价主力。",
        warning=b['warning'],
    )

    hero_rel = None
    if HERO:
        slug, idx = HERO
        items = all_photos(slug)
        if 1 <= idx <= len(items):
            nid, fn, src = items[idx - 1]
            hero_rel = build_asset(slug, nid, fn, src)

    mv = dict(m)
    mv['hero'] = hero_rel
    return mv, all_days, budget


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=int, default=1)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    content = json.load(open(os.path.join(RB, 'content.json'), encoding='utf-8'))
    meta_photos = load_meta()
    mv, all_days, budget = build_view(content, a.stage, meta_photos)
    days = [d for d in all_days if d['day'] <= a.stage]

    env = Environment(loader=FileSystemLoader(TPL), trim_blocks=True, lstrip_blocks=True)
    tpl = env.get_template('roadbook.html.j2')
    out_html = tpl.render(meta=mv, days=days, overview_days=all_days,
                          budget=budget, essentials=ESSENTIALS, stage=a.stage)

    out = a.out or os.path.join(RB, '贵州7天6晚自驾路书.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(out_html)
    print('written', out, len(out_html), 'chars')
    if mv.get('hero'):
        print('hero:', mv['hero'])
    for d in days:
        for s in d['sections']:
            print('  DAY%d %-22s 图%d  机位%d 备注%d 注意%d' % (
                d['day'], s['short'], len(s['photos']),
                sum(len(b['lines']) for b in s['shots']), len(s['tips']), len(s['notice'])))


if __name__ == '__main__':
    main()
