# -*- coding: utf-8 -*-
"""
小红书素材包索引生成器。

扫描 xhs_notes.jsonl 与 images/<note_id>/ 目录，产出 INDEX.md：
按「关键词 -> 帖子（点赞降序）」组织，每行给出笔记正文路径与该帖图片张数，
便于日后按帖子 ID 迅速定位图片归属。

用法:
    python make_xhs_index.py [--dir xhs_data]

前提：xhs_data/ 下已有 xhs_notes.jsonl（每行为一条 JSON）与 images/<note_id>/。
"""
import json
import os
import re
import sys
import argparse


def to_int(v):
    if isinstance(v, (int, float)):
        return int(v)
    s = re.sub(r"[^0-9]", "", str(v or ""))
    return int(s) if s else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="xhs_data", help="素材包根目录")
    args = ap.parse_args()

    base = args.dir
    notes_dir = os.path.join(base, "notes")
    images_dir = os.path.join(base, "images")
    jsonl = os.path.join(base, "xhs_notes.jsonl")

    rows = []
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # 按 note_id 去重，保留首次出现的完整记录
    seen, posts = set(), []
    for r in rows:
        if r["note_id"] in seen:
            continue
        seen.add(r["note_id"])
        posts.append(r)
    posts.sort(key=lambda x: -to_int(x.get("likes")))

    img_root_count = len(os.listdir(images_dir)) if os.path.isdir(images_dir) else 0

    L = ["# 小红书素材包索引", ""]
    L.append("> 共 %d 篇帖子 / %d 个图片文件夹。图片路径：`images/<帖子ID>/`" % (len(posts), img_root_count))
    L.append("> 按「关键词 → 帖子」组织，帖子按点赞数降序。")
    L.append("")

    by_kw = {}
    for r in posts:
        by_kw.setdefault(r.get("query", "未分类"), []).append(r)

    for kw in sorted(by_kw.keys()):
        items = by_kw[kw]
        L.append("## 🔍 %s（%d 篇）" % (kw, len(items)))
        L.append("")
        L.append("| 帖子ID | 标题 | 赞 | 日期 | 正文 | 图片 |")
        L.append("|---|---|---|---|---|---|")
        for r in items:
            nid = r["note_id"]
            d = os.path.join(images_dir, nid)
            n = len(os.listdir(d)) if os.path.isdir(d) else 0
            title = (r.get("title") or "").replace("|", "/")[:26]
            md_rel = os.path.join(notes_dir, nid + ".md").replace("\\", "/")
            L.append("| `%s` | %s | %d | %s | %s | %d 张 |" % (
                nid, title, to_int(r.get("likes")), r.get("date", ""), md_rel, n))
        L.append("")

    out = os.path.join(base, "INDEX.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("WROTE %s  (%d posts, %d lines)" % (out, len(posts), len(L)))


if __name__ == "__main__":
    sys.exit(main())
