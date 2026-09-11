# -*- coding: utf-8 -*-
"""
方案一 · 详细版 PPT 构建器

页序：
  01        封面（某目的地某天某晚旅游攻略）
  02        总行程（全部行 C 列骨架 + 总路线地图）
  03        人均预算
  04        出发前必看
  05 起     逐日：
              当天行程页（B+C 列 + 当天城市地图）
              每个大景点 2 页：详细页（D 列 + 景点地图 + 备注 + 注意事项）
                              照片页（小红书美景照 + 机位）
              当天收尾页（当天总备注 + 总注意事项 + 穿搭，含 🚉/🛍 非景点块）
  次尾页    物品清单
  尾页      结束祝福

管线：Jinja2 → Chrome headless 1920x1080 @2x 逐 .slide 截图 → python-pptx 13.3333x7.5in
      （封面/总行程/预算/必看/物品清单/结束页 由 slides_common 提供，与方案二共用）
"""
import os
import re
import sys

from slides_common import (BASE, ROOT, RAW, SLIDES_JSON, PHOTO_MAP, PPT, MAPS,
                           U, read_json, head_slides, tail_slides,
                           render_and_export, dedup_lines, dedup_blocks)
from nonspot_rules import KIND_ICON

TPL = os.path.join(ROOT, "templates", "ppt_detail.html.j2")
WORK = RAW
OUT_HTML = os.path.join(WORK, "detail.html")
# 自动缩排后的 DOM 快照 —— 才是真正被截图的那一版，复检/回溯都看它
OUT_FITTED = os.path.join(WORK, "detail_fitted.html")
OUT_PPTX = os.path.join(ROOT, "贵州7天6晚自驾路书_详细版.pptx")

# 大景点 → 导览地图（maps_xhs 下的 slug）
# ⚠️ 按「天 + 景点名关键词」匹配，不用 d{天}s{序号}——
#    一旦大景点列表变化（如剔除机场/车站这类非景点），序号会错位导致地图串页。
SPOT_MAP = [
    (1, "黔灵山", ("qianlingshan", "黔灵山公园 · 游玩指南")),
    (1, "青云市集", ("qingyunshiji", "青云市集 · 夜市扫街路线")),
    (2, "陡坡塘", ("doupotang", "陡坡塘瀑布 · 环形栈道")),
    (2, "黄果树大瀑布", ("huangguoshu", "黄果树大瀑布 · 水帘洞动线")),
    (2, "黄果树景区", ("huangguoshu", "黄果树景区 · 三块串联导览")),
    (3, "天星桥", ("tianxingqiao", "天星桥景区 · 下半程精华")),
    (3, "小七孔东门", ("xiaoqikong", "小七孔东门 · 梦依风情小镇")),
    (4, "小七孔", ("xiaoqikong", "荔波小七孔 · 东进东出动线")),
    (5, "西江", ("xijiang", "西江千户苗寨 · 一图看懂")),
    (6, "青岩", ("qingyan", "青岩古镇 · 南门入动线")),
    (6, "甲秀楼", ("jiaxiulou", "甲秀楼 · 南明河机位")),
    (6, "青云市集", ("qingyunshiji", "青云市集 · 补场路线")),
    # DAY7 无景点页：「特产采购」已判定为**事务节点**（非景点），不再需要导览地图
]


def spot_map_of(day, name):
    """按「天 + 名称关键词」取导览地图；找不到返回 ('', '')，由调用方告警。"""
    for d, kw, val in SPOT_MAP:
        if d == day and kw in name:
            return val
    return ("", "")


def day_slides(days, data, pmap):
    """方案一中间的逐日页面：当天行程 + 每景点 2 页 + 当天收尾。"""
    from slides_common import DAY_MAP
    out = []
    for dy in days:
        dno = dy["day"]
        cslug, ccap = DAY_MAP[dno]
        out.append({
            "kind": "dayroute",
            "label": "DAY %d" % dno,
            "day": dno,
            "date": dy["date"],
            "weekday": dy["weekday"],
            "main": dy["transport_main"],
            "transport": dy["stay_note"] if "出发地城市" not in dy["stay_note"] else "",
            "map": U(os.path.join(MAPS, cslug + ".png")),
            "map_cap": ccap,
            "brief": dy["brief"],
        })

        total = len(dy["spots"])
        for si, sp in enumerate(dy["spots"], 1):
            key = "d%ds%d" % (dno, si)
            mslug, mcap = spot_map_of(dno, sp["name"])
            if not mslug:
                print("!! 景点没有配到导览地图:", key, sp["name"])
            base = {"label": "DAY%d" % dno, "name": sp["name"],
                    "sub": "当日第 %d / %d 个大景点" % (si, total)}
            # 景点详细页
            out.append(dict(base, kind="spotdetail",
                            map=U(os.path.join(MAPS, mslug + ".png")) if mslug else "",
                            map_cap=mcap,
                            detail=sp["detail"], wear=sp["wear"],
                            avoid=sp["avoid"], notice=sp["notice"]))
            # 景点美景照 + 机位
            out.append(dict(base, kind="spotphotos",
                            photos=[U(os.path.join(PPT, r)) for r in pmap.get(key, [])],
                            shots=sp["shots"]))

        # 当天收尾
        # 「分块」结构：非景点块（机场/车站/中转站 = 交通；特产采购 = 事务）
        # 不是景点，内容不生成景点页，而是在这里单独起小标题呈现
        note_blocks, notice_blocks = [], []
        if dy["day_note"]:
            note_blocks.append({"head": "", "lines": dy["day_note"]})
        if dy["day_notice"]:
            notice_blocks.append({"head": "", "lines": dy["day_notice"]})
        for t in dy.get("nonspot_nodes", []):
            icon = KIND_ICON.get(t.get("kind"), "📍")
            # ⚠️ 只取 avoid：节点的「穿搭」已并入下方「当天穿搭建议」列，
            #    这里再写一遍就会同一页出现两次（DAY1 龙洞堡机场实测）。
            nd = list(t["avoid"])
            if nd:
                note_blocks.append({"head": icon + " " + t["name"], "lines": nd})
            nt = list(t["detail"]) + list(t["notice"])
            if nt:
                notice_blocks.append({"head": icon + " " + t["name"], "lines": nt})
        note_blocks = dedup_blocks(note_blocks)
        notice_blocks = dedup_blocks(notice_blocks)

        wear_list = dedup_lines(dy.get("day_wear") or [
            re.sub(r"^👕\s*穿搭[：:]\s*", "", w)
            for s in dy["spots"] for w in s["wear"]])

        out.append({
            "kind": "daynotes",
            "label": "DAY %d" % dno, "day": dno, "date": dy["date"],
            "note_blocks": note_blocks, "notice_blocks": notice_blocks,
            "wear": wear_list,
            "dense": (sum(len(b["lines"]) for b in note_blocks) +
                      sum(len(b["lines"]) for b in notice_blocks)) > 14,
        })
    return out


def main():
    data = read_json(SLIDES_JSON)
    pmap = read_json(PHOTO_MAP)
    meta = data["meta"]
    days = data["days"]

    slides = (head_slides(meta, days, data)
              + day_slides(days, data, pmap)
              + tail_slides(meta, days, data))

    render_and_export(slides, TPL, WORK, OUT_HTML, OUT_PPTX,
                      prefix="d", fitted_name="detail_fitted.html")


if __name__ == "__main__":
    main()
