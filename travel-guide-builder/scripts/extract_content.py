# -*- coding: utf-8 -*-
"""从攻略 xlsx 抽出结构化 content.json（路书唯一数据源）。

按【大景点】切块：D/E/H/I 四列都用同一套景点名做键，逐日对齐。

⚠️ 非景点块不是景点
-------------------
两类由 nonspot_rules 识别后**不进入 sections**（不生成景点块）：

  · 交通枢纽（🚉）：机场 / 火车站 / 高铁站 / 汽车站 / 码头 / 取还车点，
    以及标注「（中转站）」的节点；
  · 事务节点（🛍）：特产采购 / 采购 / 购物 / 手信这类办事性节点。

两者内容都降级为当日「交通节点 / 事务节点」，并入 day_notice。
"""
import os, re, json, sys
from openpyxl import load_workbook

import nonspot_rules as T

sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(BASE, "贵州7天6晚自驾攻略_10.1-10.7.xlsx")
OUT = os.path.join(BASE, "roadbook", "content.json")

# 景点名（带「区域·」前缀）→ (图片 slug, 地图 slug)
# 有序：先长后短，避免「黄果树景区」抢走「黄果树大瀑布」
SPOT_RULES = [
    ("龙洞堡",     (None,          "longdongbao")),
    ("黔灵山",     ("qianlingshan", "qianlingshan")),
    ("青云市集",   ("qingyunshiji", "qingyunshiji")),
    ("黄果树大瀑布", ("huangguoshu", "huangguoshu")),
    ("黄果树景区", ("huangguoshu",  "huangguoshu")),
    ("陡坡塘",     ("doupotang",    "doupotang")),
    ("天星桥",     ("tianxingqiao", "tianxingqiao")),
    ("小七孔东门", ("xiaoqikong",   "xiaoqikong")),
    ("荔波小七孔", ("xiaoqikong",   "xiaoqikong")),
    ("小七孔",     ("xiaoqikong",   "xiaoqikong")),
    ("卧龙潭",     ("wolongtan",    "xiaoqikong")),
    ("荔波县城",   ("libo_city",    "libo_city")),
    ("荔波",       ("libo_city",    "libo_city")),
    ("西江",       ("xijiang",      "xijiang")),
    ("青岩",       ("qingyan",      "qingyan")),
    ("甲秀楼",     ("jiaxiulou",    "jiaxiulou")),
    ("贵阳市区",   ("guiyang_city", "guiyang_city")),
    ("贵阳",       (None,           "guiyang_city")),
]


def match_spot(name):
    for kw, (img, mp) in SPOT_RULES:
        if kw in name:
            return img, mp
    return None, None
CITY_MAP = {1: "guiyang_city", 2: "anshun_city", 3: "libo_city",
            4: "libo_city", 5: "qdn_city", 6: "guiyang_city", 7: "guiyang_city"}
CITY_NAME = {1: "贵阳", 2: "安顺·黄果树", 3: "荔波", 4: "荔波",
             5: "黔东南·西江", 6: "贵阳", 7: "贵阳"}


def split_blocks(text):
    """拆块 → (spots, nonspots)。spots 是 [(name, body)]；nonspots 是 [(name, body, kind)]。

    · spots   ：`【景点名】` 块（含开头的无名前言，用 name=None 表示）
    · nonspots：`〔交通〕` / `〔事项〕` 块，或名字/正文命中关键词而被自动纠正的块
                kind ∈ {'transit', 'chore'}

    非景点块单独返回，绝不进 spots，避免被当成「大景点」。
    """
    spots, nonspots, pre = [], [], ''
    for name, body, kind in T.split_blocks(text):
        if kind == 'pre':
            pre = body
        elif kind in ('transit', 'chore'):
            nonspots.append((name, body, kind))
        else:
            spots.append((name, body))
    if pre:
        # 保持旧行为：前言挂在列表首位，由调用方并入「上一个 section」（首个则丢弃）
        spots.insert(0, (None, pre))
    return spots, nonspots


def lines_of(text):
    return [l.strip() for l in (text or '').split('\n') if l.strip()]


def pre_of(text):
    """取单元格里「没有【】表头的散装内容」，返回多行原文字符串；没有则 ''。"""
    for _n, b, k in T.split_blocks(text):
        if k == 'pre':
            return b
    return ''


def core(name):
    """去掉「区域·」前缀与括号补充，得到景点核心名。"""
    if not name:
        return ''
    s = name.split('·')[-1]
    s = re.sub(r'[（(].*?[)）]', '', s)
    s = re.sub(r'\s+', '', s)
    return s.strip()


def match_pick(blocks, sec, body_key=''):
    """把 H/I 列的块挂到 D 列景点上：核心名互相包含，或块正文提到该景点名。"""
    c = core(sec['name'])
    short = core(sec.get('short', ''))
    hit = []
    for n, b in blocks:
        if not n:
            continue
        cn = core(n)
        if cn and c and (cn in c or c in cn):
            hit.append((n, b))
            continue
        if short and len(short) >= 2 and short in b:
            hit.append((n, b))
    return hit


def parse_day(ws, r):
    a = (ws.cell(r, 1).value or '').replace('\u3000', ' ')
    dm = re.match(r'DAY(\d+)\s*([\d/]+)?\s*(\S*)?', a)
    day = int(dm.group(1)) if dm else r - 1
    date = (dm.group(2) or '').strip() if dm else ''
    weekday = (dm.group(3) or '').strip() if dm else ''

    b_all = (ws.cell(r, 2).value or '').strip()
    b_lines = [l.strip() for l in b_all.split('\n') if l.strip()]
    stay_note = ''
    b_main = ''
    for l in b_lines:
        if l.startswith('（') or l.startswith('('):
            stay_note = l.strip('（）() ')
            continue
        if not b_main:
            b_main = l
    b_main = re.sub(r'[（(].*?[)）]', '', b_main).strip()
    # 模板里的占位说明不是真实内容，剔除
    if '出发地城市' in stay_note or '住宿城市→' in stay_note:
        stay_note = ''
    stay_note = stay_note.replace('住宿城市：', '').strip()
    parts = re.split(r'[→✈➔➜]|->', b_main)
    parts = [p.strip() for p in parts if p.strip()]
    frm = parts[0] if parts else b_main
    to = parts[-1] if len(parts) > 1 else ''

    brief = lines_of(ws.cell(r, 3).value)
    food = lines_of(ws.cell(r, 6).value)
    hotel = lines_of(ws.cell(r, 7).value)

    blocks_d, nonspot_d = split_blocks(ws.cell(r, 4).value)
    blocks_e, _nonspot_e = split_blocks(ws.cell(r, 5).value)   # 机场/车站/采购无机位，丢弃
    # H / I 列：景点块参与「挂载」，非景点块单独走下面（带 🚉/🛍 前缀并入当日备注/注意事项）
    blocks_h, nonspot_h = split_blocks(ws.cell(r, 8).value)
    blocks_i, nonspot_i = split_blocks(ws.cell(r, 9).value)

    sections = []
    for name, body in blocks_d:
        if name is None:
            if sections:
                sections[-1]['detail'] += '\n' + body
            continue
        img_slug, map_slug = match_spot(name)
        sections.append(dict(
            name=name, short=core(name),
            slug=img_slug, map=map_slug,
            detail=body, shots=[], tips=[], notice=[],
        ))

    # ---- E 列：机位（按小景点分块），能对上 D 列就挂上去，否则留日级 ----
    # 属于非景点块（机场/车站/中转站/特产采购）的机位一律丢弃 —— 它们不是景点
    nonspot_cores = [core(n) for n, _b, _k in nonspot_d if n]

    def belongs_to_nonspot(nm):
        cn = core(nm)
        if not cn:
            return False
        return any(tc and (cn in tc or tc in cn) for tc in nonspot_cores)

    day_shots = []
    for n, b in blocks_e:
        ls = lines_of(b)
        if not ls:
            continue
        if n and belongs_to_nonspot(n):
            continue
        placed = False
        if n:
            cn = core(n)
            for s in sections:
                # 也允许用「完整景点名」匹配，让子景点机位能挂到父景点
                # 例：「小七孔东门」→「荔波·小七孔东门 · 梦依风情小镇」
                if cn and (cn in s['short'] or s['short'] in cn or cn in s['name']):
                    s['shots'].append(dict(name=n, lines=ls))
                    placed = True
                    break
        if not placed:
            day_shots.append(dict(name=n or '当日机位', lines=ls))

    # ---- H / I 列 ----
    day_tips, day_notice = [], []
    used_h, used_i = set(), set()
    for s in sections:
        for n, b in match_pick(blocks_h, s):
            s['tips'].extend(lines_of(b))
            used_h.add(n)
        for n, b in match_pick(blocks_i, s):
            s['notice'].extend(lines_of(b))
            used_i.add(n)
    for n, b in blocks_h:
        if n and n not in used_h:
            day_tips.append(dict(name=n, lines=lines_of(b)))
    for n, b in blocks_i:
        if n and n not in used_i:
            day_notice.append(dict(name=n, lines=lines_of(b)))

    # ---- 没有【】表头的「散装内容」（如 DAY7 的 I 列 ①-⑤ 还车注意事项）----
    # 不兜住就会整段丢掉，所以单独收集成无名块（模板里 name 为空时不渲染小标题）
    loose_tips = T.clean_items(lines_of(pre_of(ws.cell(r, 8).value)))
    loose_notice = T.clean_items(lines_of(pre_of(ws.cell(r, 9).value)))
    if loose_tips:
        day_tips.append(dict(name='', lines=loose_tips))
    if loose_notice:
        day_notice.append(dict(name='', lines=loose_notice))

    # ---- 非景点块（交通枢纽 🚉 / 事务节点 🛍）不是景点：内容降级到当日备注 / 注意事项
    day_nonspot = []
    for n, b, k in nonspot_d:
        ls = lines_of(b)
        if not ls:
            continue
        day_nonspot.append(dict(name=n, kind=k, lines=ls))
    # D 列的（取车/还车流程、采购清单）放最前面
    for t in reversed(day_nonspot):
        icon = T.KIND_ICON.get(t['kind'], '📍')
        label = t['name'] or T.KIND_LABEL.get(t['kind'], '节点')
        day_notice.insert(0, dict(name='%s %s' % (icon, label),
                                  lines=t['lines'], kind=t['kind']))
    # H 列的（穿搭 / 避坑）并入当日备注
    for n, b, k in nonspot_h:
        ls = lines_of(b)
        if ls:
            day_tips.append(dict(name='%s %s' % (T.KIND_ICON.get(k, '📍'), n),
                                 lines=ls, kind=k))
    # I 列的（补充注意事项）并入当日注意事项
    for n, b, k in nonspot_i:
        ls = lines_of(b)
        if ls:
            day_notice.append(dict(name='%s %s' % (T.KIND_ICON.get(k, '📍'), n),
                                   lines=ls, kind=k))

    # 机位：每个大景点下如果一条都没有，就把日级机位并到唯一 section 上
    if len(sections) == 1 and day_shots:
        sections[0]['shots'].extend(day_shots)
        day_shots = []

    return dict(day=day, date=date, weekday=weekday,
                from_city=frm, to_city=to, stay_note=stay_note,
                transport_raw=b_main,
                brief=brief, food=food, hotel=hotel,
                sections=sections, day_nonspot=day_nonspot,
                day_shots=day_shots, day_tips=day_tips, day_notice=day_notice,
                city=CITY_NAME.get(day, ''), city_map=CITY_MAP.get(day))


def parse_budget(wb):
    ws = wb['人均预算']
    title = note = warning = ''
    rows, totals = [], []
    per_weekday = per_holiday = tot_weekday = tot_holiday = delta = ''
    for r in range(1, ws.max_row + 1):
        v = [ws.cell(r, c).value for c in range(1, 7)]
        s = [str(x).strip() if x is not None else '' for x in v]
        joined = ' '.join(s)
        if '口径说明' in s[0]:
            note = s[0]
        if s[0].startswith('⚠️') or '不确定性' in s[0]:
            warning = s[0]
        if s[0] == '类别':
            headers = s
            continue
        is_total = ('合计' in s[2]) or (s[2].count('¥') and '/ 人' in s[2])
        if is_total:
            if '平日合计' in s[2]:
                continue
            totals.append(s)
            per_weekday = s[2].replace(' / 人', '').strip()
            per_holiday = s[3].replace(' / 人', '').strip()
            delta = s[4]
            m = re.search(r'平日\s*¥([\d,]+)', s[5])
            if m:
                tot_weekday = '¥' + m.group(1)
            m = re.search(r'国庆\s*¥([\d,]+)', s[5])
            if m:
                tot_holiday = '¥' + m.group(1)
            continue
        if s[2].startswith('¥') and s[3].startswith('¥'):
            rows.append(s)
    return dict(title=title, note=note, rows=rows, totals=totals, warning=warning,
                headers=headers if 'headers' in dir() else ['类别', '计价口径', '平日参考价（人均）', '国庆实际价（人均）', '涨幅', '数据来源与说明'],
                per_weekday=per_weekday, per_holiday=per_holiday,
                total_weekday=tot_weekday, total_holiday=tot_holiday, delta=delta)


def main():
    wb = load_workbook(XLSX)
    ws = wb['全部行程']
    days = [parse_day(ws, r) for r in range(2, ws.max_row + 1)]
    # 保留有景点块或有非景点块的日 —— 返程日可能一个景点都没有（只有还车/采购）
    days = [d for d in days if d['sections'] or d['day_nonspot']]

    budget = parse_budget(wb)

    ws_map = wb['景点地图']
    maps = []
    for r in range(2, ws_map.max_row + 1):
        row = [ws_map.cell(r, c).value for c in range(1, 6)]
        if row[1]:
            maps.append(dict(type=str(row[0] or ''), name=str(row[1]),
                             kw=str(row[2] or ''), link=str(row[3] or ''),
                             note=str(row[4] or '')))

    ws_pack = wb['物品清单']
    packing = []
    for r in range(1, ws_pack.max_row + 1):
        row = [ws_pack.cell(r, c).value for c in range(1, 8)]
        packing.append([str(x or '') for x in row])

    content = dict(
        meta=dict(
            title="贵州 7 天 6 晚 自驾旅游攻略",
            destination="贵州", days=7, nights=6, mode="自驾",
            dateRange="2026.10.1 - 10.7", people=2, gender="2 男",
            departure="深圳", transport="飞机往返",
            pace="舒适型 · 每日 9:00 出发", level="经济型",
            route="贵阳环线·黔中铁三角",
            stops=["贵阳", "黄果树", "荔波", "西江", "贵阳"],
            miles="约 950 km",
        ),
        budget=budget,
        days=days,
        maps=maps,
        packing=packing,
    )
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False, indent=1)
    print('written', OUT, os.path.getsize(OUT))
    print('days:', [(d['day'], len(d['sections']), [s['name'] for s in d['sections']]) for d in days])
    for d in days:
        if d['day_nonspot']:
            print('   DAY%d 非景点块: %s' % (
                d['day'], ['%s(%s)' % (t['name'], t['kind']) for t in d['day_nonspot']]))
    print('budget rows:', len(budget['rows']), '| totals:', len(budget['totals']))
    print('maps:', len(maps), '| packing rows:', len(packing))


if __name__ == '__main__':
    main()
