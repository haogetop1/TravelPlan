# -*- coding: utf-8 -*-
"""非景点块（non-spot block）统一判定规则 —— xlsx → HTML → PPT 三段共用。

为什么需要这个模块
------------------
行程表里除了**景区**，还混着两类「不是景点、却有自己的一整块内容」的东西：

  · **交通枢纽**：机场、火车站、高铁站、汽车站、码头、航站楼、
    取车点 / 还车点 / 租车点，以及标注「（中转站）」的过境节点。
  · **事务节点**：特产采购、采购 / 采买 / 购物、手信 / 伴手礼、纪念品…

它们**没有**「景点详细行程」「最佳机位」「美景实拍」这些概念。
一旦被当成大景点，会在整条链路上被逐级放大成荒唐的结果：

    龙洞堡机场 → 景点详细页 + 小红书美景照页 + 最佳机位
              → 连「候机厅落地窗」都成了机位；
    特产采购   → 也占一个景点页 + 一页「机位」

所以两类都必须**不进景点列表**，内容降级为**当日「交通节点 / 事务节点」**，
并入当天的备注与注意事项。

书写约定（源表 xlsx 的 D / E / H / I 四列）
------------------------------------------
    景点块        ：`【景点名】`                → 进景点列表，占景点页
    交通枢纽块    ：`〔交通〕节点名`            → 不进景点列表
    事务节点块    ：`〔事项〕节点名`            → 不进景点列表

只有 `【】` 会被当作大景点。
（即使误写成 `【】`，只要名字命中关键词也会被自动纠正，属双重保险。）
"""
import re

# ── 交通枢纽：命中即判为非景点
TRANSIT_KW = [
    "机场", "火车站", "高铁站", "动车站", "城际站", "汽车站", "客运站",
    "长途站", "码头", "航站楼", "取车点", "还车点", "租车点", "提车点",
    "登机", "中转站", "中转",
]
# ── 事务节点：非交通、但也非景点
CHORE_KW = [
    "特产采购", "采购", "采买", "购物", "手信", "伴手礼", "纪念品",
    "买特产", "买买买",
]

TRANSIT_RE = re.compile("|".join(re.escape(k) for k in TRANSIT_KW))
CHORE_RE = re.compile("|".join(re.escape(k) for k in CHORE_KW))

# ── 正文开头的「（中转站）」标注
BODY_MARK_RE = re.compile(r"^\s*[（(]\s*中转站\s*[)）]")

# ── 块标记：`【景点名】` / `〔交通〕节点名` / `〔事项〕节点名`（须在行首）
BLOCK_RE = re.compile(
    r"(?:^|\n)[ \t]*【([^】\n]{1,30})】"
    r"|(?:^|\n)[ \t]*〔\s*交通\s*〕([^\n]{0,30})"
    r"|(?:^|\n)[ \t]*〔\s*事项\s*〕([^\n]{0,30})"
)

TRANSIT_TAG = "〔交通〕"
CHORE_TAG = "〔事项〕"

# 非景点块在「当日备注 / 注意事项」里的前置图标
KIND_ICON = {"transit": "🚉", "chore": "🛍"}
KIND_LABEL = {"transit": "交通节点", "chore": "事务节点"}


def is_transit(name, body=""):
    """名字命中交通关键词，或正文以「（中转站）」开头 → 交通枢纽。"""
    n = (name or "").strip()
    if n and TRANSIT_RE.search(n):
        return True
    if body and BODY_MARK_RE.match(body):
        return True
    return False


def is_chore(name, body=""):
    """名字命中事务关键词 → 事务节点（特产采购这类）。"""
    return bool((name or "").strip()) and bool(CHORE_RE.search(name))


def is_nonspot(name, body=""):
    """既不是交通枢纽也不是景点 → False；两类非景点之一 → True。"""
    return is_transit(name, body) or is_chore(name, body)


def kind_of(name, body=""):
    """返回 'transit' / 'chore' / 'spot'。"""
    if is_transit(name, body):
        return "transit"
    if is_chore(name, body):
        return "chore"
    return "spot"


def tag_of(kind):
    return TRANSIT_TAG if kind == "transit" else CHORE_TAG


def split_blocks(text):
    """把单元格拆成块。

    返回 [(name, body, kind), ...]
      · name = None 表示块前的前言（kind='pre'）
      · kind ∈ {'pre', 'spot', 'transit', 'chore'}
    """
    if not text:
        return []
    text = str(text)
    ms = list(BLOCK_RE.finditer(text))
    if not ms:
        t = text.strip()
        return [(None, t, "pre")] if t else []

    out = []
    lead = text[:ms[0].start()].strip()
    if lead:
        out.append((None, lead, "pre"))
    for i, m in enumerate(ms):
        gi = 1 if m.group(1) is not None else (2 if m.group(2) is not None else 3)
        name = (m.group(gi) or "").strip()
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        body = text[m.end():end].strip("\n").strip()
        if gi == 1:                                  # 写成 【X】，按名字/正文判类型
            kind = kind_of(name, body)
        else:                                        # 已显式标注 〔交通〕/〔事项〕
            kind = "transit" if gi == 2 else "chore"
        out.append((name, body, kind))
    return out


MARK_ONLY_RE = re.compile(r"^\s*[（(]\s*中转站\s*[)）]\s*$")


def clean_items(ls):
    """非景点块正文转成条目：去掉行首「·」「•」，丢掉只有「（中转站）」的占位行。"""
    out = []
    for x in ls:
        x = str(x).strip()
        x = re.sub(r"^[·•・]\s*", "", x).strip()
        if not x or MARK_ONLY_RE.match(x):
            continue
        out.append(x)
    return out


def remark_in_text(text):
    """把文本里属于非景点的 `【X】` 改写成 `〔交通〕X` / `〔事项〕X`。

    返回 (新文本, [(名字, kind), ...])。判定与 split_blocks 一致；
    正文一字不动，只换标记。
    """
    text = str(text or "")
    ms = list(BLOCK_RE.finditer(text))
    if not ms:
        return text, []

    edits, changed = [], []
    for i, m in enumerate(ms):
        nxt = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        if m.group(1) is None:                     # 已是 〔…〕 标注，跳过
            continue
        name = m.group(1).strip()
        body = text[m.end():nxt].strip("\n").strip()
        k = kind_of(name, body)
        if k == "spot":
            continue
        changed.append((name, k))
        # m.start(1)-1 / m.end(1)+1 正好框住「【」与「】」
        edits.append((m.start(1) - 1, m.end(1) + 1, tag_of(k) + name))

    if not edits:
        return text, []
    out, last = [], 0
    for s, e, rep in edits:
        out.append(text[last:s])
        out.append(rep)
        last = e
    out.append(text[last:])
    return "".join(out), changed
