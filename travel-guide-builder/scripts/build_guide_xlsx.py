# -*- coding: utf-8 -*-
"""
通用旅游攻略 xlsx 生成器。

用法:
    python build_guide_xlsx.py content.json output.xlsx

content.json 结构（详见 examples/guizhou_content_sample.json）:
{
  "itinerary": {
    "headers": ["日期","大交通",...9列...],
    "widths":  [11,20,26,62,30,40,40,52,44],
    "row_height": 300,
    "keys": ["A","B","C","D","E","F","G","H","I"],
    "rows": [{"A":"DAY1\\n10/1","B":"...", ...}, ...]
  },
  "budget": {
    "title": "...",
    "note": "口径说明",
    "headers": ["类别","计价口径","平日价","节假日价","涨幅","数据来源"],
    "widths": [18,30,18,18,10,68],
    "rows": [[...6列...], ...],
    "total": [["","","平日合计","节假日合计","",""], ["","","¥x / 人","¥y / 人","1.6×","说明"]],
    "warning": "价格时效与不确定性说明"
  },
  "fee_template": {
    "headers": ["日期","支出项目",...13列...],
    "widths": [14,22,...],
    "categories": ["门票","购物","餐饮","交通","住宿","其他"],
    "totals":     ["总计","交通","购物","门票","餐饮","住宿","其他"]
  },
  "packing": [[ "常用必备","穿戴洗漱",... ], [ "充电宝","墨镜",... ], ...],  # 第 1 行为表头
  "packing_width": 20,
  "maps": [[ "类型","名称","搜索词","链接","备注" ], [ ... ], ...],
  "map_widths": [16,30,26,62,46]
}

说明: budget / fee_template / packing / maps 均为可选，缺哪个就不生成对应 sheet。
费用明细只写模板骨架（表头 + 类别 + 总计标签），不填任何数值。
"""
import json
import sys
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

BROWN = "B08968"
CREAM = "FAF7F2"
RED = "C00000"
BROWN_TEXT = "7A5C3E"

_thin = Side(style="thin", color="D9CFC4")
BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
WRAP = Alignment(wrap_text=True, vertical="top", horizontal="left")
WRAP_C = Alignment(wrap_text=True, vertical="center", horizontal="center")

F_HEAD = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
F_BODY = Font(name="微软雅黑", size=10)
F_DAY = Font(name="微软雅黑", size=11, bold=True, color=BROWN_TEXT)
F_TOTAL = Font(name="微软雅黑", size=12, bold=True, color=RED)
F_TITLE = Font(name="微软雅黑", size=14, bold=True, color=BROWN_TEXT)
F_SMALL = Font(name="微软雅黑", size=9, color="8A7A6A")
F_WARN = Font(name="微软雅黑", size=9, color=RED)

FILL_HEAD = PatternFill("solid", fgColor=BROWN)
FILL_CREAM = PatternFill("solid", fgColor=CREAM)


def col_letter(i):
    """1-based 列号 -> A1 样式列字母（支持 >26 列）"""
    s = ""
    while i > 0:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def put(ws, r, c, value, font=F_BODY, fill=None, align=WRAP, height=None):
    cell = ws.cell(row=r, column=c, value=value)
    cell.font = font
    cell.alignment = align
    cell.border = BORDER
    if fill:
        cell.fill = fill
    if height:
        ws.row_dimensions[r].height = height
    return cell


def set_widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[col_letter(i)].width = w


def sheet_itinerary(wb, cfg):
    ws = wb.active
    ws.title = "全部行程"
    keys = cfg.get("keys", list("ABCDEFGHI"))
    for c, h in enumerate(cfg["headers"], start=1):
        put(ws, 1, c, h, F_HEAD, FILL_HEAD, WRAP_C, height=34)
    set_widths(ws, cfg.get("widths", [26] * len(cfg["headers"])))
    for r, row in enumerate(cfg["rows"], start=2):
        for c, k in enumerate(keys, start=1):
            v = row.get(k, "")
            if c == 1:
                put(ws, r, c, v, F_DAY, FILL_CREAM, WRAP_C)
            else:
                put(ws, r, c, v, F_BODY)
        ws.row_dimensions[r].height = cfg.get("row_height", 300)
    ws.freeze_panes = "C2"
    return ws


def sheet_budget(wb, cfg):
    ws = wb.create_sheet("人均预算")
    ncol = len(cfg["headers"])
    put(ws, 1, 1, cfg.get("title", "人均总预算"), F_TITLE)
    note = cfg.get("note", "")
    if note:
        c = put(ws, 2, 1, note, F_SMALL)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncol)
        ws.row_dimensions[2].height = 46
    for i, h in enumerate(cfg["headers"], start=1):
        put(ws, 4, i, h, F_HEAD, FILL_HEAD, WRAP_C)
    set_widths(ws, cfg.get("widths", [18] * ncol))
    r = 5
    for row in cfg["rows"]:
        for i, v in enumerate(row, start=1):
            put(ws, r, i, v, F_BODY, FILL_CREAM if r % 2 == 0 else None)
        ws.row_dimensions[r].height = 62
        r += 1
    for row in cfg.get("total", []):
        is_head = str(row[2]).endswith("合计")
        f = F_HEAD if is_head else F_TOTAL
        fill = FILL_HEAD if is_head else FILL_CREAM
        for i, v in enumerate(row, start=1):
            put(ws, r, i, v, f, fill, WRAP_C)
        ws.row_dimensions[r].height = 32 if is_head else 42
        r += 1
    warn = cfg.get("warning", "")
    if warn:
        r += 1
        c = put(ws, r, 1, warn, F_WARN)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncol)
        ws.row_dimensions[r].height = 40
    return ws


def sheet_fee_template(wb, cfg):
    """费用明细：只生成模板骨架，不填任何数值。"""
    ws = wb.create_sheet("费用明细")
    for i, h in enumerate(cfg["headers"], start=1):
        put(ws, 1, i, h, F_HEAD, FILL_HEAD, WRAP_C)
    ws.row_dimensions[1].height = 40
    set_widths(ws, cfg.get("widths", [14] * len(cfg["headers"])))
    cat_col = cfg.get("category_col", 3)
    tot_col = cfg.get("total_col", 11)
    for i, cat in enumerate(cfg.get("categories", []), start=2):
        put(ws, i, cat_col, cat, F_BODY, FILL_CREAM if i % 2 == 0 else None, WRAP_C)
    for i, lab in enumerate(cfg.get("totals", []), start=2):
        put(ws, i, tot_col, lab, F_BODY, FILL_CREAM if i % 2 == 0 else None, WRAP_C)
    ws.freeze_panes = "A2"
    return ws


def sheet_packing(wb, rows, width=20):
    ws = wb.create_sheet("物品清单")
    for r, row in enumerate(rows, start=1):
        for c, v in enumerate(row, start=1):
            if r == 1:
                put(ws, r, c, v, F_HEAD, FILL_HEAD, WRAP_C, height=26)
            else:
                put(ws, r, c, v, F_BODY, FILL_CREAM if r % 2 == 0 else None)
    ncol = max(len(r) for r in rows)
    set_widths(ws, [width] * ncol)
    return ws


def sheet_maps(wb, rows, widths=None):
    ws = wb.create_sheet("景点地图")
    for r, row in enumerate(rows, start=1):
        for c, v in enumerate(row, start=1):
            if r == 1:
                put(ws, r, c, v, F_HEAD, FILL_HEAD, WRAP_C)
            else:
                put(ws, r, c, v, F_BODY, FILL_CREAM if r % 2 == 0 else None)
        ws.row_dimensions[r].height = 30
    set_widths(ws, widths or [20] * max(len(r) for r in rows))
    return ws


def verify(path, cfg):
    """回读校验：非空 + 乱码扫描 + 数字自洽。返回问题列表。"""
    from openpyxl import load_workbook
    issues = []
    wb = load_workbook(path)
    ws = wb["全部行程"]
    keys = cfg["itinerary"].get("keys", list("ABCDEFGHI"))
    # 高频乱码子串（按项目可自行扩充）
    noise = ["点开", "樹果", "QAQ", "锟斤拷", "???", "***"]
    for r in range(2, 2 + len(cfg["itinerary"]["rows"])):
        for c, k in enumerate(keys, start=1):
            v = ws.cell(r, c).value
            if not v:
                issues.append(f"[空] 全部行程 r{r} 列{k}")
                continue
            for n in noise:
                if n in str(v):
                    issues.append(f"[乱码?] 全部行程 r{r} 列{k} 含 '{n}'")
    return wb.sheetnames, issues


def build(content, out):
    wb = Workbook()
    sheet_itinerary(wb, content["itinerary"])
    if content.get("budget"):
        sheet_budget(wb, content["budget"])
    if content.get("fee_template"):
        sheet_fee_template(wb, content["fee_template"])
    if content.get("packing"):
        sheet_packing(wb, content["packing"], content.get("packing_width", 20))
    if content.get("maps"):
        sheet_maps(wb, content["maps"], content.get("map_widths"))
    wb.save(out)
    sheets, issues = verify(out, content)
    print("SAVED:", out)
    print("sheets:", sheets)
    if issues:
        print("!! 校验未通过:")
        for i in issues:
            print("   ", i)
    else:
        print("OK: 回读校验通过")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        content = json.load(f)
    build(content, sys.argv[2])
