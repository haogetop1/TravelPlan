# -*- coding: utf-8 -*-
"""
按「景点语义」把现有照片分配到各大景点（人工确认版）。

⚠️ 键的稳定性（2026-09-10 修正）
--------------------------------
旧版按 `d{天}s{序号}` 指定，一旦大景点列表变化（例如剔除机场/车站这类
非景点后少了一页），**序号整体错位**，照片就会张冠李戴。
现在改成按「天 + 景点名关键词」指定，实际序号从 slides.json 现算，
列表怎么变都不会串页。

为什么不用自动打分：黄果树景区 / 大瀑布 / 陡坡塘 三页同属一个景区，
自动分配会把同一组 huangguoshu 照片整组回填给多页 → 三页长得一模一样。
所以这里**逐张指定**，并保证：
  · 复用只发生在「同一地点」或「同一城市」的页面上，语义自洽；
  · 排除了「其实是地图/文字长图」的伪照片；
  · 每页 3~4 张。

产出 roadbook/_raw/detail/photo_map.json + assign_a/b.jpg 核对图
"""
import os
import json
import re
from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.abspath(__file__))
PPT = os.path.join(BASE, "roadbook", "assets", "ppt")
OUT_DIR = os.path.join(BASE, "roadbook", "_raw", "detail")
SLIDES = os.path.join(OUT_DIR, "slides.json")
os.makedirs(OUT_DIR, exist_ok=True)

# ---- 逐页指定：(天, 景点名关键词, 照片, 备注标签)
# 顺序有意义：第 1 张是「主图」，必须是最出片的风景照，人像放末位。
# 已排除的伪照片：anshun_city/03(手绘地图) anshun_city/04(文字长图)
#                libo_city/01(招牌) libo_city/02(菜单) libo_city/03(人像+菜单)
#                xijiang/02(与 xijiang_night/02 重复) tianxingqiao/03(商铺)
#                doupotang/01(人像) wolongtan/01(人像+水印) xijiang/01(人像)
ASSIGN = [
    # DAY1 ─────────────────────────────────────────────
    (1, "黔灵山", ["qianlingshan/02.jpg", "qianlingshan/04.jpg",
                   "qianlingshan/01.jpg", "qianlingshan/03.jpg"]),
    (1, "青云市集", ["qingyunshiji/02.jpg", "qingyunshiji/03.jpg",
                     "qingyunshiji/01.jpg", "qingyunshiji/04.jpg"]),
    # DAY2 ── 黄果树三块：三页来源各异，绝不同图
    (2, "黄果树景区", ["anshun_city/01.jpg", "anshun_city/02.jpg",
                       "huangguoshu/03.jpg"]),
    (2, "陡坡塘", ["doupotang/03.jpg", "doupotang/02.jpg", "doupotang/04.jpg"]),
    (2, "黄果树大瀑布", ["huangguoshu/01.jpg", "huangguoshu/02.jpg",
                         "huangguoshu/04.jpg"]),
    # DAY3 ─────────────────────────────────────────────
    (3, "天星桥", ["tianxingqiao/02.jpg", "tianxingqiao/01.jpg",
                   "tianxingqiao/04.jpg"]),
    (3, "小七孔东门", ["wolongtan/02.jpg", "wolongtan/03.jpg", "wolongtan/04.jpg"]),
    # DAY4 ── 小七孔整条沟的标志性画面全留给它
    (4, "小七孔", ["xiaoqikong/01.jpg", "xiaoqikong/02.jpg",
                   "xiaoqikong/03.jpg", "xiaoqikong/04.jpg"]),
    # DAY5 ── 西江：夜景全景打头，白天田园跟上
    (5, "西江", ["xijiang_night/02.jpg", "xijiang/04.jpg",
                 "xijiang_night/01.jpg", "xijiang/03.jpg"]),
    # DAY6 ─────────────────────────────────────────────
    (6, "青岩", ["qingyan/02.jpg", "qingyan/04.jpg",
                 "qingyan/03.jpg", "qingyan/01.jpg"]),
    (6, "甲秀楼", ["jiaxiulou/01.jpg", "jiaxiulou/03.jpg",
                   "jiaxiulou/04.jpg", "jiaxiulou/02.jpg"]),
    (6, "青云市集", ["qingyunshiji/02.jpg", "qingyunshiji/03.jpg",
                     "qingyunshiji/04.jpg"]),
    # DAY7 现在没有景点页了 —— 「特产采购」已判定为**事务节点**（非景点），
    # 不再占景点页 / 机位页，所以这里不需要照片分配。
]


def resolve(slides):
    """把「(天, 关键词)」解析成 d{天}s{序号} → 照片列表。"""
    out, unmatched, labels = {}, [], {}
    for day in slides["days"]:
        d = day["day"]
        for i, sp in enumerate(day["spots"], 1):
            nm = sp["name"]
            pick = None
            for dd, kw, photos in ASSIGN:
                if dd == d and kw in nm:
                    pick = photos
                    break
            key = "d%ds%d" % (d, i)
            labels[key] = nm
            if pick:
                out[key] = list(pick)
            else:
                unmatched.append((key, nm))
    return out, unmatched, labels


def contact(rows, path, title):
    TH_W, TH_H, PAD, LBL = 210, 145, 6, 18
    COLS = 4
    W = COLS * TH_W + (COLS + 1) * PAD
    H = len(rows) * (TH_H + LBL + PAD) + PAD + 24
    cv = Image.new("RGB", (W, H), (250, 247, 242))
    dr = ImageDraw.Draw(cv)
    dr.text((PAD, 5), title, fill=(140, 106, 79))
    for i, (key, label, photos) in enumerate(rows):
        y = PAD + 24 + i * (TH_H + LBL + PAD)
        dr.rectangle([PAD, y, W - PAD, y + LBL], fill=(176, 137, 104))
        dr.text((PAD + 5, y + 3), "%s  %s  n=%d" % (key, label, len(photos)),
                fill=(255, 255, 255))
        for j, rel in enumerate(photos[:COLS]):
            try:
                im = Image.open(os.path.join(PPT, rel)).convert("RGB")
            except Exception:
                continue
            im.thumbnail((TH_W - 4, TH_H - 2))
            cv.paste(im, (PAD + j * TH_W + 2, y + LBL + 1))
    cv.save(path, "JPEG", quality=88)
    print("WROTE", path, cv.size)


def main():
    slides = json.load(open(SLIDES, encoding="utf-8"))
    photo_map, unmatched, labels = resolve(slides)
    keys = sorted(photo_map.keys(),
                  key=lambda k: (int(re.match(r"d(\d+)s", k).group(1)),
                                 int(re.search(r"s(\d+)$", k).group(1))))

    missing = [r for v in photo_map.values() for r in v
               if not os.path.exists(os.path.join(PPT, r))]
    if missing:
        print("!! 缺文件:", missing)
        return

    from collections import Counter
    cnt = Counter(r for v in photo_map.values() for r in v)
    reused = {k: n for k, n in cnt.items() if n > 1}
    print("=== 校验 ===")
    print("景点页数 =", len(keys), "（源表大景点总数）")
    print("照片总引用 =", sum(len(v) for v in photo_map.values()),
          " 唯一照片 =", len(cnt))
    print("复用照片 =", reused if reused else "无")
    if unmatched:
        print("!! 没有指定照片的景点（会显示为空白页）:")
        for k, nm in unmatched:
            print("   ", k, nm)
    for k in keys:
        n = len(photo_map[k])
        if n < 3:
            print("  !! %s 只有 %d 张" % (k, n))

    with open(os.path.join(OUT_DIR, "photo_map.json"), "w", encoding="utf-8") as f:
        json.dump(photo_map, f, ensure_ascii=False, indent=2)
    print("WROTE", os.path.join(OUT_DIR, "photo_map.json"))

    rows = [(k, labels.get(k, ""), photo_map[k]) for k in keys]
    half = max(1, len(rows) // 2)
    contact(rows[:half], os.path.join(OUT_DIR, "assign_a.jpg"), "分配核对 A")
    contact(rows[half:], os.path.join(OUT_DIR, "assign_b.jpg"), "分配核对 B")


main()
