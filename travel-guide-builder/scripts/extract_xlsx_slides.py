# -*- coding: utf-8 -*-
"""
方案一（详细版 PPT）数据抽取器。

数据源：贵州7天6晚自驾攻略_10.1-10.7.xlsx  →  sheet「全部行程」
列映射（1-based）：
  A 日期 | B 大交通 | C 简要行程 | D 详细行程 | E 机位
  F 餐饮 | G 酒店 | H 备注(穿衣和避坑) | I 注意事项(预约/买票/行程等)

D / E / H / I 四列均为「【景点名】内容……」的分块结构，
且 H / I 末尾各有一段 `📌 当日总XX：……` 的当日汇总 —— 单独抽出来。

⚠️ 非景点块不是景点
-------------------
两类由 nonspot_rules 识别，**不生成景点页**（既不进 spotdetail 也不进 spotphotos）：

  · 交通枢纽（🚉）：机场 / 火车站 / 高铁站 / 汽车站 / 码头 / 取还车点，
    以及标注「（中转站）」的节点；
  · 事务节点（🛍）：特产采购 / 采购 / 购物 / 手信这类办事性节点。

两者内容都降级为当日「交通节点 / 事务节点」，并入 day_note / day_notice。

产出：roadbook/_raw/detail/slides.json
"""
import os
import re
import json

import openpyxl

import nonspot_rules as T

BASE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(BASE, "贵州7天6晚自驾攻略_10.1-10.7.xlsx")
OUT_DIR = os.path.join(BASE, "roadbook", "_raw", "detail")
OUT = os.path.join(OUT_DIR, "slides.json")

MATCH_THRESHOLD = 0.5


# ---------------------------------------------------------------- 基础工具

def cell(ws, r, c):
    v = ws.cell(r, c).value
    return "" if v is None else str(v)


def lines(text):
    return [x.strip() for x in text.split("\n") if x.strip()]


def dedup_keep(seq):
    """按前 20 字去重，保留原顺序。"""
    seen, out = set(), []
    for x in seq:
        x = str(x).strip()
        k = re.sub(r"\s+", "", x)[:20]
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def split_blocks(text):
    """把 【名】内容 / 〔交通〕名 内容 / 〔事项〕名 内容 切成 [(name, body, kind)]，
    返回 (blocks, tail_pm)。

    kind ∈ {'pre', 'spot', 'transit', 'chore'}；'pre' 表示块前没有标记的散装内容。
    tail_pm 为末尾 📌 段落（从最后一个块里摘出来）。
    """
    blocks = T.split_blocks(text)
    tail_pm = ""
    if blocks:
        name, body, kind = blocks[-1]
        m = re.search(r"📌", body)
        if m:
            head = body[:m.start()].strip()
            tail_pm = body[m.start():].strip()
            blocks[-1] = (name, head, kind)
    else:
        m = re.search(r"📌.*", str(text or ""), re.S)
        tail_pm = m.group(0).strip() if m else ""
    return blocks, tail_pm


def pm_lines(pm):
    """📌 段 → 去掉标题行后的条目列表。"""
    if not pm:
        return []
    out = []
    for ln in lines(pm):
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("📌"):
            rest = re.sub(r"^📌\s*[^：:]*[：:]?\s*", "", ln).strip()
            if rest:
                out.append(rest)
            continue
        out.append(ln)
    return out


# 城市前缀：必须后接分隔符「·」/空白，或正好到结尾。
# ⚠️ 不能写成 ^(荔波)[·\s]* —— 那样「荔波县城」会被剥成「县城」，
#    再和【荔波】块就配不上了（DAY3 中转站踩过这个坑）。
CITY_STRIP = re.compile(
    r"^(贵阳市区|贵阳市|贵阳|安顺|黔东南|黔南|黔西南|荔波|深圳|遵义|凯里|雷山|铜仁|镇远)"
    r"(?:[·\s]+|$)"
)


def _norm(s):
    s = re.sub(r"\s+", "", s or "")
    # 反复剥掉开头的城市前缀，避免「贵阳·甲秀楼」和「贵阳·青云市集」因「贵阳」二字互相误匹配
    for _ in range(3):
        t = CITY_STRIP.sub("", s)
        if t == s or not t:
            break
        s = t
    return s


def match_score(spot, block):
    """景点名 ↔ 块名的相似度，0~1（已剥离城市前缀）。"""
    s, b = _norm(spot), _norm(block)
    if not s or not b:
        return 0.0
    if s == b:
        return 1.0
    if s in b or b in s:
        return 0.9
    ss, sb = set(s), set(b)
    return len(ss & sb) / len(ss)


def pick_block(spot, blocks):
    """为景点挑最匹配的块，低于阈值返回 (None, '')。"""
    best, best_sc = None, 0.0
    for name, body in blocks:
        sc = match_score(spot, name)
        if sc > best_sc:
            best, best_sc = (name, body), sc
    if best_sc < MATCH_THRESHOLD:
        return None, ""
    return best


# ---------------------------------------------------------------- 主流程

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb["全部行程"]

    days = []
    for r in range(2, ws.max_row + 1):
        a = cell(ws, r, 1)
        if not a.strip():
            continue
        a_lines = lines(a)
        day_no = int(re.search(r"DAY\s*(\d+)", a_lines[0]).group(1))
        # A 列形如 "DAY1\n10/1 周四"：第 2 行才是日期
        date_line = a_lines[1] if len(a_lines) > 1 else ""
        m_d = re.match(r"(\S+)\s*(周.)", date_line)
        date_lbl = m_d.group(1) if m_d else date_line
        weekday = m_d.group(2) if m_d else ""

        b_txt = cell(ws, r, 2)
        b_lines = lines(b_txt)
        transport_main = b_lines[0] if b_lines else ""
        # B 列第 2 行是住宿城市说明
        stay_note = b_lines[1] if len(b_lines) > 1 else ""
        c_txt = cell(ws, r, 3)
        d_txt = cell(ws, r, 4)
        e_txt = cell(ws, r, 5)
        f_txt = cell(ws, r, 6)
        g_txt = cell(ws, r, 7)
        h_txt = cell(ws, r, 8)
        i_txt = cell(ws, r, 9)

        d_raw, _ = split_blocks(d_txt)
        e_raw, _ = split_blocks(e_txt)
        h_raw, h_pm = split_blocks(h_txt)
        i_raw, i_pm = split_blocks(i_txt)

        # ---- 剔除非景点块：机场/车站/中转站/特产采购 都不参与景点页
        spot_d = [(n, b) for n, b, k in d_raw if k == "spot"]
        nonspot_d = [(n, b, k) for n, b, k in d_raw if k in ("transit", "chore")]
        # E 列：非景点块的机位一律丢掉（不是景点，不需要机位）
        _ncores = [_norm(n) for n, _b, _k in nonspot_d if n]

        def _is_nonspot_name(nm):
            cn = _norm(nm)
            return bool(cn) and any(tc and (cn in tc or tc in cn)
                                    for tc in _ncores)

        spot_e = [(n, b) for n, b, k in e_raw
                  if k == "spot" and not _is_nonspot_name(n)]
        h_blocks = [(n, b) for n, b, k in h_raw if k != "pre"]
        i_blocks = [(n, b) for n, b, k in i_raw if k != "pre"]
        # 没有【】表头的散装内容（如 DAY7 的 I 列 ①-⑤ 还车注意事项）→ 并入当日注意事项
        loose_notice = []
        for n, b, k in i_raw:
            if k == "pre":
                loose_notice.extend(T.clean_items(lines(b)))
        for n, b, k in h_raw:
            if k == "pre":
                loose_notice.extend(T.clean_items(lines(b)))

        # ---- 酒店：G 列形如「🏨【...】\n酒店A\n酒店B\n📕【...】\n· ...」
        hotel_groups, cur = [], None
        for ln in lines(g_txt):
            if ln.startswith("🏨") or ln.startswith("📕") or ln.startswith("⚠️"):
                cur = {"head": ln, "items": []}
                hotel_groups.append(cur)
            elif cur is not None:
                cur["items"].append(ln)
            else:
                cur = {"head": "", "items": [ln]}
                hotel_groups.append(cur)

        # ---- 餐饮：F 列，前 3 行是三餐，其余是注解
        food_ln = lines(f_txt)
        meals, extras = [], []
        for ln in food_ln:
            if re.match(r"^[🌅🍜🍲🥤]", ln):
                if len(meals) < 3:
                    meals.append(ln)
                else:
                    extras.append(ln)
            else:
                extras.append(ln)

        # ---- 景点（只含真正的景区 / 景点，交通枢纽已在上面剔除）
        spots = []
        used_h, used_i = set(), set()
        for name, body in spot_d:
            # 机位兜底①：单景点日 → E 列写的是该景点内部的子机位（古桥/跌水/卧龙潭…），
            # 必须全收，否则会被子串匹配抢先只取到一条
            if len(spot_d) == 1 and spot_e:
                merged = []
                for _nm, bd in spot_e:
                    merged.extend([x for x in lines(bd) if x.strip()])
                ename, ebody = "%s（子机位）" % name, "\n".join(merged)
            else:
                ename, ebody = pick_block(name, spot_e)

            hname, hbody = pick_block(name, h_blocks)
            iname, ibody = pick_block(name, i_blocks)
            if hname:
                used_h.add(hname)
            if iname:
                used_i.add(iname)

            # 机位兜底②：容器型景点（如「黄果树景区」）自身无机位 →
            # 合并同日**名称相近**的子景点机位
            if not ename:
                merged = []
                for oname, _obody in spot_d:
                    if oname == name:
                        continue
                    if match_score(oname, name) < MATCH_THRESHOLD:
                        continue
                    onm, obd = pick_block(oname, spot_e)
                    if obd:
                        merged.extend([x for x in lines(obd) if x.strip()])
                if merged:
                    ename, ebody = "%s（含子景点）" % name, "\n".join(merged)

            h_lines = lines(hbody)
            wear = [x for x in h_lines if x.startswith("👕")]
            avoid = [x for x in h_lines if re.match(r"^[⚠️❶❷❸❹❺❻❼❽❾❿]", x)]
            notice_items = [x for x in lines(ibody)]

            spots.append({
                "name": name,
                "detail": lines(body),
                "shots": [x for x in lines(ebody) if x.startswith("·") or x.strip()],
                "shots_src": ename,
                "wear": wear,
                "avoid": avoid,
                "notice": notice_items,
                "tips_src": hname,
            })

        # ---- 非景点块：不生成景点页，降级为当日「交通节点 / 事务节点」
        nonspot_nodes = []
        for tname, tbody, tkind in nonspot_d:
            th, tb = pick_block(tname, [(n, b) for n, b in h_blocks
                                        if n not in used_h])
            ti, tib = pick_block(tname, [(n, b) for n, b in i_blocks
                                         if n not in used_i])
            if th:
                used_h.add(th)
            if ti:
                used_i.add(ti)
            hl = lines(tb)
            nonspot_nodes.append({
                "name": tname,
                "kind": tkind,
                "detail": T.clean_items(lines(tbody)),
                "wear": [re.sub(r"^👕\s*穿搭[：:]\s*", "", x)
                         for x in hl if x.startswith("👕")],
                "avoid": [re.sub(r"^[⚠️\s]+", "", x)
                          for x in hl if re.match(r"^[⚠️]", x)
                          and not re.fullmatch(r"[⚠️\s]*避坑[：:]?", x.strip())]
                         + [x for x in hl if re.match(r"^[❶❷❸❹❺❻❼❽❾❿]", x)],
                "notice": [re.sub(r"^[①-⑳\s]+", "", x)
                           for x in lines(tib) if x.strip()],
            })

        # ---- 当日备注 / 注意事项 / 穿搭：📌 汇总 + 未挂上的孤立块
        #     非景点块的内容不在这里拍平，保留 nonspot_nodes 结构，
        #     由 build_ppt_detail.py 在收尾页起小标题单独呈现。
        day_note = pm_lines(h_pm)
        day_notice = pm_lines(i_pm) + loose_notice
        day_wear = []
        for _n, _b in h_blocks:
            for x in lines(_b):
                if x.startswith("👕"):
                    day_wear.append(re.sub(r"^👕\s*穿搭[：:]\s*", "", x))

        for n, b in h_blocks:
            if n and n not in used_h:
                day_note.extend(x for x in T.clean_items(lines(b))
                                if not x.startswith("👕"))
        for n, b in i_blocks:
            if n and n not in used_i:
                day_notice.extend(T.clean_items(lines(b)))

        days.append({
            "day": day_no,
            "date": date_lbl,
            "weekday": weekday,
            "stay_note": stay_note,
            "transport_main": transport_main,
            "transport": lines(b_txt),
            "brief": lines(c_txt),
            "meals": meals,
            "food_extras": extras,
            "hotel_groups": hotel_groups,
            "spots": spots,
            "nonspot_nodes": nonspot_nodes,
            "day_note": dedup_keep(day_note),
            "day_notice": dedup_keep(day_notice),
            "day_wear": dedup_keep(day_wear),
        })

    # ---------- 出发前必看：从 I 列抽「需提前/预约/下单」条目，从 H 列抽避坑
    # 注意：非景点块（机场/车站/中转站/特产采购）的需提前项也要算进来
    #（例：DAY1「神州租车需提前 3-7 天下单」），否则会漏掉关键预约项
    book_lines, avoid_top, wear_all = [], [], []
    for d in days:
        sources = [(s["notice"], s["avoid"], s["wear"]) for s in d["spots"]]
        for t in d.get("nonspot_nodes", []):
            sources.append((t["notice"], t["avoid"],
                            ["👕 穿搭：" + w for w in t["wear"]]))
        for notice, avoid, wear in sources:
            for n in notice:
                if re.search(r"(预约|提前\s*\d|小程序|下单|锁定|提前订|抢)", n):
                    book_lines.append(re.sub(r"^[①-⑳\s]+", "", n))
            for a in avoid:
                a2 = re.sub(r"^[⚠️❶❷❸❹❺❻❼❽❾❿\s]+", "", a)
                if a2 and "避坑" not in a2:
                    avoid_top.append(a2)
            for w in wear:
                wear_all.append(re.sub(r"^👕\s*穿搭[：:]\s*", "", w))

    def dedup(seq, cap):
        seen, out = set(), []
        for x in seq:
            k = re.sub(r"\s+", "", x)[:18]
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
            if len(out) >= cap:
                break
        return out

    # ---------- 预算（人均预算 sheet）
    wb2 = openpyxl.load_workbook(XLSX, data_only=True)
    bs = wb2["人均预算"]
    budget = {"title": cell(bs, 1, 1), "note": cell(bs, 2, 1),
              "headers": [cell(bs, 4, c) for c in range(1, 7)], "rows": []}
    for r in range(5, 12):
        row = [cell(bs, r, c) for c in range(1, 7)]
        if any(row):
            budget["rows"].append(row)
    for r in range(12, bs.max_row + 1):
        row = [cell(bs, r, c) for c in range(1, 7)]
        if any(x.strip() for x in row):
            budget.setdefault("totals", []).append(row)

    # ---------- 物品清单
    ws3 = wb2["物品清单"]
    packing = []
    for c in range(1, ws3.max_column + 1):
        head = cell(ws3, 1, c)
        if not head.strip():
            continue
        items = []
        for r in range(2, ws3.max_row + 1):
            v = cell(ws3, r, c).strip()
            if v:
                items.append(v)
        packing.append({"head": head, "items": items})

    # ---------- 费用明细空表（用于第4页参考）
    ws4 = wb2["费用明细"]
    expense_cats = []
    for r in range(2, ws4.max_row + 1):
        v = cell(ws4, r, 3).strip()
        if v:
            expense_cats.append(v)

    payload = {
        "meta": {"dest": "贵州", "days": 7, "nights": 6, "mode": "自驾",
                 "dateRange": "2026.10.1 - 10.7"},
        "days": days,
        "budget": budget,
        "packing": packing,
        "expense_cats": expense_cats,
        "preflight": {
            "book": dedup(book_lines, 10),
            "avoid": dedup(avoid_top, 8),
            "wear": dedup(wear_all, 8),
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---------- 摘要
    print("WROTE", OUT)
    print("days =", len(days), " spots =", sum(len(d["spots"]) for d in days))
    for d in days:
        print("\n--- DAY%d %s %s  (%s)"
              % (d["day"], d["date"], d["weekday"], d["stay_note"]))
        print("   brief行=%d  meals=%d  hotel组=%d  当日总备注=%d  当日总注意=%d  穿搭=%d"
              % (len(d["brief"]), len(d["meals"]), len(d["hotel_groups"]),
                 len(d["day_note"]), len(d["day_notice"]), len(d["day_wear"])))
        if d["nonspot_nodes"]:
            print("   非景点块（不生成景点页）: %s"
                  % ['%s[%s]' % (t["name"], t["kind"]) for t in d["nonspot_nodes"]])
        for s in d["spots"]:
            print("   · %-24s detail=%-2d shots=%-2d(%-10s) wear=%d avoid=%d notice=%d"
                  % (s["name"][:24], len(s["detail"]), len(s["shots"]),
                     (s["shots_src"] or "-")[:10], len(s["wear"]),
                     len(s["avoid"]), len(s["notice"])))
    print("\npreflight: book=%d avoid=%d wear=%d"
          % (len(payload["preflight"]["book"]), len(payload["preflight"]["avoid"]),
             len(payload["preflight"]["wear"])))
    print("budget rows=%d totals=%d packing组=%d expense_cats=%d"
          % (len(budget["rows"]), len(budget.get("totals", [])),
             len(packing), len(expense_cats)))


main()
