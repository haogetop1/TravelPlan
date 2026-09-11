# -*- coding: utf-8 -*-
"""
方案二 · 简洁版 PPT 构建器

页序（20 页）：
  01        封面（某目的地某天某晚旅游攻略）
  02        总行程（全部行 C 列骨架 + 总路线地图）
  03        人均预算
  04        出行前必看
  05 起     逐日 × 7 天，每天 2 页：
              A 当天行程规划页（B 列时间轴 + 推荐机位 + 备注穿搭 + 避坑注意事项）
              B 当天餐饮住宿页（三餐 + 特色美食饮品 + 住宿推荐）
  次尾页    物品清单
  尾页      结束祝福

与方案一（详细版）的关系：
  · 封面 / 总行程 / 人均预算 / 出行前必看 / 物品清单 / 结束页 **完全共用**
    —— 由 slides_common 的 head_slides / tail_slides 提供，模板走 `_ppt_shared_pages.j2`，
       保证两套 PPT 这些页面的文案与版式逐字节一致。
  · 只有中间的逐日页面不同：方案一按「景点」铺开（信息全、页数多），
    方案二按「天」收拢（一天两页，一眼看完）。

管线：Jinja2 → Chrome headless 1920x1080 @2x 逐 .slide 截图 → python-pptx
"""
import os
import re

from slides_common import (ROOT, RAW, SLIDES_JSON,
                           head_slides, tail_slides, render_and_export,
                           dedup_lines, dedup_blocks)
from nonspot_rules import KIND_ICON

TPL = os.path.join(ROOT, "templates", "ppt_simple.html.j2")
WORK = RAW                       # 与方案一共用素材目录，靠文件名前缀 "c" 区分
OUT_HTML = os.path.join(WORK, "simple.html")
# 自动缩排后的 DOM 快照 —— 才是真正被截图的那一版
OUT_FITTED = os.path.join(WORK, "simple_fitted.html")
OUT_PPTX = os.path.join(ROOT, "贵州7天6晚自驾路书_简洁版.pptx")


def strip_bullet(s):
    """源表条目常以「· 」开头，PPT 里已用圆点符号，去掉会重复。"""
    return re.sub(r"^[·•\-]\s*", "", (s or "").strip())


def dedup(seq):
    """兼容旧调用：等同 slides_common.dedup_lines。"""
    return dedup_lines(seq)


def non_spot_blocks(dy):
    """非景点块（🚉 交通 / 🛍 事务）拆成「备注·穿搭」与「避坑·注意事项」两组。

    这些块**不是景点**，不生成独立页，只在当日页里起小标题呈现。
    归类原则：穿搭 / 总备注 → 备注·穿搭（吃住页）；避坑 + 说明 + 注意事项 → 避坑页。
    最后统一走 dedup_blocks 做**跨块**去重 —— 同一句常同时出现在当日总备注与某个节点块里。
    """
    wear_lines = list(dy.get("day_note") or []) + list(dy.get("day_wear") or [])
    notice_lines = list(dy.get("day_notice") or [])
    wear_extra, notice_extra = [], []
    for t in dy.get("nonspot_nodes", []):
        icon = KIND_ICON.get(t.get("kind"), "📍")
        head = "%s %s" % (icon, t["name"])
        if t.get("wear"):
            wear_extra.append({"head": head, "lines": list(t["wear"])})
        # 「避坑」在语义上属于注意事项，归到避坑页
        nt = list(t.get("detail", [])) + list(t.get("avoid", [])) + list(t.get("notice", []))
        if nt:
            notice_extra.append({"head": head, "lines": nt})

    wear_blocks = [{"head": "", "lines": dedup_lines(wear_lines)}] if wear_lines else []
    wear_blocks += wear_extra
    notice_blocks = [{"head": "", "lines": dedup_lines(notice_lines)}] if notice_lines else []
    notice_blocks += notice_extra
    return dedup_blocks(wear_blocks), dedup_blocks(notice_blocks)


def hotel_blocks(dy):
    """住宿分组 → 结构化行（区域标签 / 具体酒店），模板才能渲染出层级。"""
    out = []
    for g in dy.get("hotel_groups", []):
        rows = []
        for it in g.get("items", []):
            txt = (it or "").strip()
            if not txt:
                continue
            # 「· 汉庭…」是酒店行；「黄果树镇区（…）：」这类是区域标签
            rows.append({"kind": "item", "text": strip_bullet(txt)}
                        if re.match(r"^[·•\-]\s", it)
                        else {"kind": "label", "text": txt})
        if g.get("head") or rows:
            out.append({"head": (g.get("head") or "").strip(), "rows": rows})
    return out


def day_slides(days):
    """方案二中间的逐日页面：每天 2 页（行程规划 + 餐饮住宿）。"""
    out = []
    for dy in days:
        dno = dy["day"]
        wear_blocks, notice_blocks = non_spot_blocks(dy)
        # 推荐机位：把当天各景点的机位按景点分组
        shot_groups = [{"name": sp["name"], "shots": sp["shots"]}
                       for sp in dy["spots"] if sp.get("shots")]
        stay = dy.get("stay_note") or ""
        out.append({
            "kind": "dayplan",
            "label": "DAY %d" % dno, "day": dno,
            "date": dy["date"], "weekday": dy["weekday"],
            "main": dy["transport_main"],
            "brief": dy["brief"],
            "shot_groups": shot_groups,
            "notice_blocks": notice_blocks,
            "foot_note": stay if "出发地城市" not in stay else "",
        })

        hotels = hotel_blocks(dy)
        n_rows = sum(len(g["rows"]) for g in hotels)
        out.append({
            "kind": "daystay",
            "label": "DAY %d" % dno, "day": dno,
            "date": dy["date"], "weekday": dy["weekday"],
            "main": dy["transport_main"],
            "meals": dy.get("meals", []),
            "food_extras": [strip_bullet(x) for x in dy.get("food_extras", [])],
            "hotel_groups": hotels,
            "hotel_dense": n_rows > 12,
            "wear_blocks": wear_blocks,
        })
    return out


def main():
    import json
    with open(SLIDES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    meta, days = data["meta"], data["days"]

    slides = (head_slides(meta, days, data)
              + day_slides(days)
              + tail_slides(meta, days, data))

    render_and_export(slides, TPL, WORK, OUT_HTML, OUT_PPTX,
                      prefix="c", fitted_name="simple_fitted.html")


if __name__ == "__main__":
    main()
