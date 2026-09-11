#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""地图来源登记与图注生成。

2026-09-11 用户确定的优先级（上一层拿不到 / 甄别不过，才降级下一层）：

    ① xhs       小红书搜到的大景点地图（博主手绘导览图 / 导览牌实拍）
    ② tianditu  天地图网页截图
    ③ amap      高德 Web 服务静态地图（需用户自备 key）
    ④ other     其它保底（景区官网导览图等）

用法（roadbook 目录指含 assets/maps/ 的那一级）：

    python map_sources.py <roadbook目录> --init
        扫描 assets/maps/*.png，生成 _sources.json 骨架（source 为 unknown，待填）

    python map_sources.py <roadbook目录> --set <slug> <source> [credit]
        登记来源。source 取 xhs / tianditu / amap / other
        例：python map_sources.py . --set chaka xhs "@某某 · 5f3a2b1c" --verified

    python map_sources.py <roadbook目录> --check
        校验：每张图是否登记来源、xhs 来源是否已过甄别、是否有孤儿条目。
        有 FAIL 时退出码为 1（适合接进 CI / 回读校验环节）

    python map_sources.py <roadbook目录> --caption <slug>
        打印该 slub 应使用的图注（模板统一在这里，避免正文手写错来源）
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

# source -> (显示名, 图注模板)
PRIORITY = {
    "xhs":      ("① 小红书大景点导览图",
                 "图源：小红书 {credit} ，实际导航以官方地图为准"),
    "tianditu": ("② 天地图网页截图",
                 "地图来源：天地图（自然资源部 & NavInfo）　|　审图号 GS（2025）1508 号"),
    "amap":     ("③ 高德 Web 服务静态地图",
                 "地图来源：高德地图　|　审图号 GS（2018）1729 号"),
    "other":    ("④ 其它保底来源",
                 "地图来源：{credit}"),
}
ORDER = ["xhs", "tianditu", "amap", "other"]


def maps_dir(root):
    return os.path.join(root, "assets", "maps")


def src_path(root):
    return os.path.join(maps_dir(root), "_sources.json")


def load_sources(root):
    p = src_path(root)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("读取 %s 失败：%s" % (p, e))
        return {}


def save_sources(root, data):
    p = src_path(root)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return p


def list_pngs(root):
    d = maps_dir(root)
    if not os.path.isdir(d):
        return []
    return sorted(f[:-4] for f in os.listdir(d) if f.lower().endswith(".png"))


def caption(slug, info):
    """按登记的来源生成图注；未登记时给占位（提示要去补登记）。"""
    src = (info or {}).get("source", "unknown")
    credit = ((info or {}).get("credit") or "").strip()
    if src in PRIORITY:
        name, tpl = PRIORITY[src]
        if src == "xhs" and not credit:
            credit = "(待填作者与帖子ID)"
        if src == "other" and not credit:
            credit = "(待填来源出处)"
        return tpl.format(credit=credit)
    return "地图来源：(待登记，见 assets/maps/_sources.json)"


def cmd_init(root):
    pngs = list_pngs(root)
    data = load_sources(root)
    added = 0
    for s in pngs:
        if s not in data:
            data[s] = {"source": "unknown", "credit": "", "verified": False, "note": ""}
            added += 1
    # 清掉已不存在的图
    stale = [k for k in data if k not in pngs]
    for k in stale:
        del data[k]
    p = save_sources(root, data)
    print("已生成 %s：%d 张地图，新增登记 %d 条%s"
          % (p, len(pngs), added, ("，清除孤儿条目 %d 条" % len(stale)) if stale else ""))
    print("下一步：按优先级补 sources —— xhs(①) > tianditu(②) > amap(③) > other(④)")


def cmd_set(root, argv):
    if len(argv) < 2:
        print("用法：--set <slug> <source> [credit] [--verified]")
        return
    slug, src = argv[0], argv[1]
    rest = argv[2:]
    verified = "--verified" in rest
    rest = [x for x in rest if x != "--verified"]
    credit = rest[0] if rest else ""
    if src not in PRIORITY:
        print("未知来源 %r，可选：%s" % (src, " / ".join(ORDER)))
        return
    data = load_sources(root)
    data.setdefault(slug, {})
    data[slug].update({"source": src, "credit": credit, "verified": verified})
    save_sources(root, data)
    print("已登记 %s -> %s | 图注：%s" % (slug, PRIORITY[src][0], caption(slug, data[slug])))


def cmd_caption(root, argv):
    if not argv:
        print("用法：--caption <slug>")
        return
    data = load_sources(root)
    info = data.get(argv[0])
    print(caption(argv[0], info))


def cmd_check(root):
    pngs = list_pngs(root)
    data = load_sources(root)
    fails, warns = [], []

    for slug in pngs:
        info = data.get(slug) or {}
        src = info.get("source", "unknown")
        if src not in PRIORITY:
            fails.append("%s：未登记来源（当前 %r）—— 图注会变成占位串" % (slug, src))
            continue
        if src == "xhs":
            if not info.get("verified"):
                fails.append("%s：来源为小红书但 verified=False —— ① 必须先过四项甄别"
                             "（图上地名 / 帖文语境 / 相对位置 / 非拼贴），不用就降级到 ②" % slug)
            if not (info.get("credit") or "").strip():
                warns.append("%s：小红书来源缺 credit（作者 · 帖子ID），图注无法溯源" % slug)
        if src == "other" and not (info.get("credit") or "").strip():
            fails.append("%s：④ 保底来源必须写明出处，无法确认出处的图宁可不放" % slug)

    for slug in data:
        if slug not in pngs:
            warns.append("%s：_sources.json 里有登记但没有对应图片" % slug)

    print("=== 地图来源校验（①xhs > ②tianditu > ③amap > ④other）===")
    print("图片总数 %d，已登记 %d" % (len(pngs), sum(1 for s in pngs if data.get(s, {}).get("source") in PRIORITY)))
    for slug in pngs:
        info = data.get(slug) or {}
        src = info.get("source", "unknown")
        name = PRIORITY.get(src, ("未登记", ""))[0]
        print("  %-16s %-24s %s" % (slug, name, caption(slug, info)))

    # 同目录落一份 markdown 报告，方便回读
    rep = os.path.join(maps_dir(root), "MAP_SOURCES.md")
    with open(rep, "w", encoding="utf-8") as f:
        f.write("# 地图来源登记表\n\n")
        f.write("优先级：① 小红书 > ② 天地图 > ③ 高德API > ④ 保底。\n\n")
        f.write("| slug | 来源 | verified | 图注 |\n|---|---|---|---|\n")
        for slug in pngs:
            info = data.get(slug) or {}
            src = info.get("source", "unknown")
            f.write("| %s | %s | %s | %s |\n"
                    % (slug, PRIORITY.get(src, ("未登记", ""))[0],
                       info.get("verified", ""), caption(slug, info)))
        if fails or warns:
            f.write("\n## 待处理\n\n")
            for x in fails:
                f.write("- [FAIL] %s\n" % x)
            for x in warns:
                f.write("- [WARN] %s\n" % x)
    print("\n报告已写入 %s" % rep)

    for x in fails:
        print("FAIL %s" % x)
    for x in warns:
        print("WARN %s" % x)
    print("\n结果：FAIL %d / WARN %d" % (len(fails), len(warns)))
    return 1 if fails else 0


USAGE = __doc__


def main():
    argv = [a for a in sys.argv[1:]]
    if not argv:
        print(USAGE)
        return 0
    root = argv[0]
    rest = argv[1:]
    if not os.path.isdir(maps_dir(root)):
        print("找不到 %s —— 请传入含 assets/maps/ 的 roadbook 目录" % maps_dir(root))
        return 1
    if "--init" in rest:
        cmd_init(root)
        return 0
    if "--check" in rest:
        return cmd_check(root)
    if "--set" in rest:
        cmd_set(root, [x for x in rest[rest.index("--set") + 1:]])
        return 0
    if "--caption" in rest:
        cmd_caption(root, [x for x in rest[rest.index("--caption") + 1:]])
        return 0
    print(USAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
