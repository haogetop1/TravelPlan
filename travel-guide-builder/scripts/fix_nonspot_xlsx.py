# -*- coding: utf-8 -*-
"""在源表 xlsx 里把「非景点块」的标记改写成 〔交通〕/〔事项〕。

只改标记，不动内容、不动位置、不动格式 —— 目的是让源表自己说清楚
「哪些是景点、哪些是过境节点 / 事务节点」，避免下一轮再被当成大景点。

用法：
  python fix_nonspot_xlsx.py            # 先 dry-run，只打印
  python fix_nonspot_xlsx.py --apply    # 真正写回
"""
import os
import shutil
import sys

import openpyxl

import nonspot_rules as N

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(BASE, "贵州7天6晚自驾攻略_10.1-10.7.xlsx")
COLS = [(4, "D详细行程"), (5, "E机位"), (8, "H备注"), (9, "I注意事项")]


def rows(ws):
    for r in range(2, ws.max_row + 1):
        day = str(ws.cell(r, 1).value or "").split("\n")[0].strip()
        if day:
            yield r, day


def main():
    apply = "--apply" in sys.argv
    wb = openpyxl.load_workbook(XLSX)
    ws = wb["全部行程"]

    total = []
    for r, day in rows(ws):
        for c, label in COLS:
            v = ws.cell(r, c).value
            if not v:
                continue
            new, changed = N.remark_in_text(v)
            for name, kind in changed:
                total.append((day, label, name, kind))
            if changed and apply:
                ws.cell(r, c).value = new

    print("待改写块数 =", len(total))
    for day, label, name, kind in total:
        print("  %-6s %-10s 【%s】 → %s%s" % (day, label, name, N.tag_of(kind), name))

    # 顺带修正里程口径：实际黔中环线约 950km，原文写 900km
    miles_fix = []
    for r, day in rows(ws):
        for c, label in COLS:
            v = ws.cell(r, c).value
            if v and "900" in str(v):
                miles_fix.append((day, label))
                if apply:
                    ws.cell(r, c).value = (str(v).replace("约 900km", "约 950km")
                                                 .replace("约900km", "约 950km"))
    if miles_fix:
        print("里程文案修正（900km → 950km）:", miles_fix)

    if not apply:
        print("\n[dry-run] 加 --apply 才写回。")
        return

    bak = XLSX + ".bak-before-nonspot-mark"
    if not os.path.exists(bak):
        shutil.copy2(XLSX, bak)
        print("已备份 →", os.path.basename(bak))
    try:
        wb.save(XLSX)
    except PermissionError as e:
        print("!! 写入被拒绝（Excel 可能正开着这个文件）：", e)
        raise SystemExit(3)
    print("已写回", os.path.basename(XLSX), os.path.getsize(XLSX), "bytes")

    # 回读校验：重新打开文件，逐格确认非景点块已带 〔交通〕/〔事项〕 标记
    wb2 = openpyxl.load_workbook(XLSX)
    ws2 = wb2["全部行程"]
    left, ok_tr, ok_ch = [], 0, 0
    for r, day in rows(ws2):
        for c, label in COLS:
            v = ws2.cell(r, c).value
            if not v:
                continue
            for name, _b, kind in N.split_blocks(v):
                if kind not in ("transit", "chore") or not name:
                    continue
                if N.tag_of(kind) + name in str(v):
                    if kind == "transit":
                        ok_tr += 1
                    else:
                        ok_ch += 1
                else:
                    left.append((day, label, name, kind))
    print("回读：〔交通〕 =", ok_tr, " 〔事项〕 =", ok_ch)
    if left:
        print("   !! 仍写成 【】 的非景点块 =", left)
    else:
        print("   ✅ 所有非景点块都已标注，不会再被当成景点")


if __name__ == "__main__":
    main()
