# 图文路书流水线（HTML / PPT / PDF）

从「攻略 xlsx」到「图文并茂路书三件套」的可复用流程。
数据流是**单向**的：xlsx → `content.json` → HTML / PPT / PDF，
所以改内容只需改 xlsx 或 content.json，模板永远不用动。

```
攻略.xlsx ──roadbook_extract_content.py──▶ roadbook/content.json
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
        roadbook_build_html.py      roadbook_build_ppt.py      （共用同一份 JSON）
                    │                         │
                    ▼                         ▼
            路书.html  ──roadbook_print_pdf.py──▶  路书.pdf
                    │
                    └──roadbook_inline_html.py──▶ 单文件版.html（图片 base64，可直接转发）
```

## 一、目录约定

```
guizhou_trip/
├── 贵州7天6晚自驾攻略.xlsx        # 上游攻略表（9 列结构见 column-rules.md）
├── content.json 相关脚本
└── roadbook/
    ├── content.json               # 唯一数据源
    ├── templates/roadbook.html.j2 # HTML 模板
    ├── assets/maps/*.png          # 高德官方地图截图
    ├── assets/img/<slug>/*.jpg    # 已压缩的实拍图（生成时自动产出）
    └── _raw/
        ├── photos/<slug>/<note_id>/NN.jpg   # 小红书原图（按景点+帖子两级分类）
        ├── contact2/<slug>.jpg              # 粗筛 contact sheet
        ├── review/<slug>_review.jpg         # 精选放大复核图
        └── shots/seg_NN.jpg                 # HTML 渲染截图（验收用）
```

## 二、执行顺序

```bash
PY="<venv>/python.exe"

# 1. xlsx → content.json（按【大景点】切块，跨列对齐）
$PY roadbook_extract_content.py

# 2. 挑图：先粗筛看全貌，再过一张放大复核图确认
$PY xhs_make_contact.py <slug>...            # 生成 contact sheet
$PY xhs_list_picks.py <slug>                 # 打印「编号 → 路径 + 来源帖」
$PY xhs_review_picks.py <slug> "3,9,13,17"   # 放大复核候选，读图确认

# 3. 把选中的编号 + 文案填进 roadbook_build_html.py 的 PICKS / HERO
# 4. 出产物
$PY roadbook_build_html.py --stage 1         # 先出封面+总篇章+DAY1
$PY html_screenshot.py                       # 分段截图验收
$PY roadbook_print_pdf.py                    # HTML → PDF（版式一致）
$PY roadbook_build_ppt.py --stage 1
$PY ppt_layout_check.py                      # PPT 版式自检
$PY roadbook_inline_html.py                   # 单文件版（转发用）
# 5. 确认后全量
$PY roadbook_build_html.py --stage 7 && $PY roadbook_print_pdf.py && $PY roadbook_build_ppt.py --stage 7
```

## 三、必须遵守的硬约束

### 1. 地图合规（不能省）
- **只用官方地图服务**：高德（或天地图）。**不要 AI 自绘中国地图轮廓** —— 地理精度不保证
  且有合规风险。
- 截图时**必须保留「地图审图号 GS(20xx)xxxx 号」和「甲测资字」这类版权声明**，
  路书里每张地图的图注都要写出来源。
- 截图的可行手法与坑（共 6 次试错，别再走一遍）见 `scraping-playbook.md`
  的「高德地图截图」一节。

### 2. HTML 与 PDF 内容/版式必须完全一致
PDF 由 `roadbook_print_pdf.py` 用同一份 HTML 打印（`emulate_media('print')`），
**不要另写一套 PDF 模板**。打印 CSS 里给 `.card / figure / .ph / .bud-row`
加 `break-inside:avoid`，否则卡片会被分页切断。

### 3. 图片必须有来源标注
每张实拍图下面标 `📷 小红书 @作者 · 帖子ID`，可溯源、尊重原创。
`_photos.jsonl` 里记录了 author/note_id，`roadbook_build_html.py` 会读它生成 credit。

### 4. 编辑接口（不能只读）
HTML 里给可编辑文本打了 `data-edit` 属性，右下角「✎ 编辑模式」开关 +
「⇩ 导出修改」按钮，导出 `content_overrides.json` 回灌。
改内容有两条路：**改 content.json 重跑**（推荐）或 **页面内改 + 导出**。

### 5. PPT 版式自检必须跑
`ppt_layout_check.py` 会算每个文本框的**文本容量**（CJK 按 1 字宽折算）与越界，
在交付前把「文字溢出画面」这类问题拦下来。**issues 必须为 0 再交付。**

## 四、踩过的坑

| 坑 | 现象 | 正解 |
|---|---|---|
| Jinja2 把 CSS 当注释 | `TemplateSyntaxError: Missing end of comment tag` | CSS 里 `{` 紧跟 `#`（如 `@media print{#editbar`）会被当成 `{#`。写成 `{ #editbar` 或加空格 |
| PPT 出现空白页 | 新建 `s2` 后仍用 `s` 写入，内容叠到上一页 | 新建 slide 后**逐个替换变量**，别只改 `s2 = blank()` 一行 |
| 封面塌陷 | 没有 hero 图时 `.cover` 高度为 0 | 给 `.cover` 兜底 `min-height` + 渐变背景；`cover-inner` 是绝对定位，不撑高度 |
| 总览只显示部分天 | 阶段限制同时裁掉了总览时间轴 | 视图模型分 `days`（受 stage 限制）与 `overview_days`（恒为全部） |
| 移动端表格挤成一团 | 6 列预算表在 430px 屏上不可读 | 一行一卡：左「类别+涨幅」、中「平日/国庆」双价块、下「计价口径」、来源放 `<details>` 折叠 |
| 模板占位文字混进正文 | B 列括号里的「出发地城市→住宿城市」被当成真实内容 | 解析时**过滤模板占位串**（`出发地城市` / `住宿城市→`） |
| `**加粗**` 原样显示 | 注释里的 markdown 语法 | 自写 `rich()`：转义 → 把 `【xx】` 与 `**xx**` 换成 `<b>`，输出 `|safe` |
| PPT 里景点分类错 | content.json 没有 `kind` 字段 | 分类要在消费端现算（`sec_kind(name)`），别指望上游 JSON 带 |
| 图片裁切把人像切掉 | `object-fit:cover` 居中裁剪 | 纵向裁剪时按 **0.42** 的偏置而不是 0.5，保留画面上部（人像/瀑布主体多在上半） |

## 五、成本与耗时参考（贵州 7 天 6 晚 / 2 人 / 自驾）

| 环节 | 实测 |
|---|---|
| 小红书原图采集 | 16 个景点；每景点 2-3 关键词 × 取 6 帖；约 12 分钟（后台跑，含限速） |
| 采集产出 | 423 张可用原图（900-1600px，176-800KB/张） |
| 挑图 | contact sheet 粗筛 + 逐景点 1 张放大复核图 |
| 地图 | 15 张高德截图（审图号完整） |
| 出产物 | 阶段一（封面+总篇章+DAY1）HTML 43KB / PDF 12 页 / PPT 10 页 |
