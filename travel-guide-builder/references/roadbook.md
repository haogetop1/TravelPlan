# 图文路书流水线（HTML / PPT / PDF）

从「攻略 xlsx」到「图文并茂路书三件套」的可复用流程。
数据流是**单向**的：xlsx → `content.json` → HTML / PPT / PDF，
所以改内容只需改 xlsx 或 content.json，模板永远不用动。

```
攻略.xlsx ──roadbook_extract_content.py──▶ roadbook/content.json
   │
   │                        ┌─────────────────────────┼─────────────────────────┐
   │                        ▼                         ▼                         ▼
   │            roadbook_build_html.py      roadbook_build_ppt.py      （共用同一份 JSON）
   │                        │                         │
   │                        ▼                         ▼
   │                路书.html  ──roadbook_print_pdf.py──▶  路书.pdf
   │                        │
   │                        └──roadbook_inline_html.py──▶ 单文件版.html（图片 base64，可直接转发）
   │
   └─extract_xlsx_slides.py──▶ roadbook/_raw/detail/slides.json
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
        build_ppt_detail.py            build_ppt_simple.py
                    │                             │
                    ▼                             ▼
            ..._详细版.pptx（方案一）      ..._简洁版.pptx（方案二）
                    └──────────┬──────────────────┘
                               ▼
              slides_common.py（共用骨架 + 6 个共用页 + 渲染管线）
              templates/_ppt_base.css.j2 / _ppt_shared_pages.j2
```

> HTML 路书走 `content.json`，两套 PPT 走 `slides.json` —— **两条链的数据源不同**，
> 但都由同一份 `攻略.xlsx` 派生。改内容后**两条链都要重跑**。
> 两套 PPT 的详细规范见 `ppt-plans.md`。

## 一、目录约定

```
guizhou_trip/
├── 贵州7天6晚自驾攻略.xlsx        # 上游攻略表（9 列结构见 column-rules.md）
├── nonspot_rules.py               # 非景点块判定（xlsx→HTML→PPT 三段共用，唯一真源）
├── slides_common.py               # 两套 PPT 的共用骨架 + 共用页 + 渲染导出管线
├── content.json 相关脚本
└── roadbook/
    ├── content.json               # HTML 链数据源
    ├── templates/
    │   ├── roadbook.html.j2       # HTML 模板
    │   ├── _ppt_base.css.j2       # 两套 PPT 共用 CSS
    │   ├── _ppt_shared_pages.j2   # 两套 PPT 共用 6 页 HTML
    │   ├── ppt_detail.html.j2     # 方案一模板
    │   └── ppt_simple.html.j2     # 方案二模板
    ├── assets/maps/*.png          # 高德官方地图截图
    ├── assets/img/<slug>/*.jpg    # 已压缩的实拍图（生成时自动产出）
    └── _raw/
        ├── photos/<slug>/<note_id>/NN.jpg   # 小红书原图（按景点+帖子两级分类）
        ├── contact2/<slug>.jpg              # 粗筛 contact sheet
        ├── review/<slug>_review.jpg         # 精选放大复核图
        ├── shots/seg_NN.jpg                 # HTML 渲染截图（验收用）
        └── detail/                          # PPT 链
            ├── slides.json                  # 两套 PPT 的数据源
            ├── photo_map.json               # 按「天 + 景点名关键词」的配图表
            ├── detail.html / detail_fitted.html     # 方案一渲染源（fitted = 缩排后）
            ├── simple.html / simple_fitted.html     # 方案二渲染源
            ├── d_NN.png / c_NN.png          # 逐页截图（前缀区分两套）
            └── review/sheet_*.jpg           # 逐页验收联络表
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
$PY roadbook_inline_html.py                  # 单文件版（转发用）

# 6. 两套 PPT（方案一 / 方案二）
$PY extract_xlsx_slides.py                   # xlsx → slides.json（改了抽取器必须重跑）
$PY allocate_photos.py                       # 配图 → photo_map.json
$PY build_ppt_detail.py                      # 方案一 → ..._详细版.pptx
$PY build_ppt_simple.py                      # 方案二 → ..._简洁版.pptx
$PY check_detail_overflow.py                 # 方案一：卡片裁剪 + 页底溢出
$PY diag_simple_overflow.py                  # 方案二：逐卡内容高度 / 裁剪量
$PY make_detail_sheet.py && $PY make_simple_sheet.py   # 验收联络表
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
（本项目的详细版 PPT 每页是「HTML → 截图 → 满幅贴图」，
额外建议用 Playwright 量一遍每页 `scrollHeight vs clientHeight`，
比只看文本框更能抓到卡片内部被裁的情况。）

### 6. 非景点块不是景点（xlsx → HTML → PPT 全链路）
见 `column-rules.md` 的「非景点块用 `〔交通〕` / `〔事项〕`」一节。要点：

- **两类**：交通枢纽（`〔交通〕`）+ 事务节点（`〔事项〕`，如特产采购）。
- 判定规则集中在一个共享模块（本项目为 `nonspot_rules.py`），
  **HTML 链路与 PPT 链路必须引用同一份**，不要各写一套正则。
- 各列的落地：D→当日注意事项；E→丢弃；H→当日备注/穿搭；I→当日注意事项。
- **键要用「天 + 景点名」，不能用 `d{天}s{序号}`**：剔除一个非景点会让序号整体错位，
  照片与导览地图就会串页。照片 `ASSIGN` 与地图 `SPOT_MAP` 都要改成名称匹配。
- **剔除非景点后要跨块去重**：同一句常同时出现在当日总备注与某个节点块里
  （DAY7 的穿搭就是），只做块内去重会在同一页出现两遍。
- 收尾页要塞得下新增内容：条目多时自动降字号（`.dense` / `two-col`），
  并用页高检测确认没有超出 1080px。
- **链路顺序不能错**：改了抽取器就必须**重跑抽取器**再构建，
  否则会拿旧的 JSON 重新拍平，出现内容重复。
- **下游快照要一起重建**：单文件版 HTML 是主 HTML 的快照（base64 内嵌），
  改了主 HTML 之后**必须重跑 `roadbook_inline_html.py`**，否则转发版还是旧版。
- **全量构建要写全参数**：`roadbook_build_html.py` 默认 `--stage 1`（只出封面+总篇章+DAY1），
  交付前务必显式 `--stage 7`，否则会误以为「内容丢了」。

### 7. 两套 PPT 必须共用页面与同一套栅格铁律
方案一（详细版）/ 方案二（简洁版）的**页序、共用页实现、flex 铁律、实测数字
全部在 `references/ppt-plans.md`**。这里只强调三条最容易犯的：

- 共用页（封面 / 总行程 / 人均预算 / 出发前必看 / **物品清单** / **结束祝福**）
  由 `slides_common.py` 的 `head_slides()` / `tail_slides()` 统一产出，**两套都调它**，
  别复制粘贴 HTML（会漂移成「方案一说 950km、方案二说 900km」）。
- **两套都要有「次尾页物品清单 + 尾页结束祝福」**（用户明确要求）。
- 逐日页**不允许内容被静默裁掉**：构建日志出现 `⚠️ 仍差 Npx` 就必须改排版或删内容；
  排版前先量真实内容高度（`diag_simple_overflow.py`），别凭感觉估。

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
| 机场 / 特产采购被当成景点 | 拿到「景点详细页 + 美景照页 + 机位」，连候机厅落地窗都成了机位 | 源头 D/E/H/I 四列改 `〔交通〕` / `〔事项〕` 标记，并在解析层统一剔除，内容降级到当日备注/注意事项 |
| 城市前缀正则剥离过头 | `荔波县城` 被剥成 `县城`，与 `【荔波】` 块配不上 | 城市前缀正则写成 `^(城市)(?:[·\s]+\|$)`，要求后跟分隔符或正好到结尾 |
| 无 `【】` 表头的内容整段丢失 | 某天 I 列直接从 ① 开始写，旧解析只取 `📌` 段，①-⑤（含还车注意事项）被丢掉 | 「前言块」也要兜住，并进当日注意事项 |
| 序号键导致照片/地图串页 | 丢掉一个非景点后，`d1s1` 从机场变成黔灵山，照片与地图全错位 | 分配表改用「天 + 景点名关键词」匹配，序号从抽取结果现算 |
| 改了抽取器却没重跑 | 构建出的页面内容重复（旧拍平数据 + 新结构并存） | 改动链路后按 `extract → allocate → build` 顺序重跑，再看产物 |
| 跨块重复没去 | 同一句穿搭既在「当日总备注」又在「当天穿搭建议」列；DAY7 的备注·穿搭 12 行里有 9 行重复 | 用 `slides_common.dedup_blocks()` 做**跨块**去重；节点块只取 `avoid`，穿搭统一由穿搭列呈现 |
| `flex:none` 挤死 `flex:1` 兄弟 | 推荐机位被压成 **2px** 高，内容整段消失（最多裁 306px） | 长卡片改 `flex:1 1 auto`（基准=内容高度）；短卡片 `flex-shrink:0` |
| 兄弟卡写死 `flex:5 / flex:10` | 内容逐日差异极大（机位 51–497px），写死配比的日子就被裁 | 用内容自适应基准，实测「机位+避坑」最多 746px < 830px 可用 |
| `column-count` 用在窄列 | 栏宽减半 → 一条目折两行 → 高度不降反升 | 只在**通栏**（≥800px/栏）上用双栏压高度 |
| 构建脚本无脑 `rm d_*.png` | 被宿主的**批量删除保护**拦下并直接终止构建进程（本轮删到第 50 个文件时触发） | 只删「序号 > 本次页数」的超范围旧帧，别整目录清 |
| 对同一文件并行发两个 Edit | 后写覆盖前写，先前那处改动静默丢失（`import` 被还原，报 `NameError`） | 同一文件的多次编辑**串行**下发 |
| `Template(str)` 里用 `{% include %}` | `TemplateSyntaxError` | 换 `Environment(loader=FileSystemLoader(模板目录))` |
| 单文件版没跟着重建 | 主 HTML 已修好，但 `_单文件版.html` 仍是旧版（机场当景点、还带「交通枢纽」标签） | 单文件版是 HTML 的**下游快照**，改完 HTML 必须重跑 `roadbook_inline_html.py`；交付前对**每一个**产物都单独回读校验 |
| 漏写 `--stage 7` | HTML 里只有 2 个景点卡片，看着像「大部分内容丢了」 | 该脚本默认 `--stage 1`；全量交付必须显式 `--stage 7` |
| 对整页图片版 PPT 做文字扫描 | 永远查不到内容，误判「没有该页」 | 校验对象是渲染源 HTML（`detail_fitted.html` / `simple_fitted.html`）+ 逐页截图 |
| **景点卡不出图，且不报错** | `extract` 的 `SPOT_RULES` 没配 → section 的 `slug=None` → `resolve_photos()` 直接返回 `[]`，页面只是「少了实拍模块」，看日志毫无异常 | 把「景点名关键词 → 素材 slug」映射补齐；首次构建务必跑 `--stage 1` 确认目标景点「图N」不为 0 |
| **挑图挑到博主封面** | 每篇的 `01.jpg` 是博主封面，多带大字标题或多图拼贴，放进景点卡很杂 | 从 `02.jpg` 起挑；先出 contact sheet 粗筛（`xhs_make_contact.py` / 自建），再定 `PICKS` |
| **实拍图 credit 显示两行** | 卡片 `.author` 的 `innerText` 混进了发布日期（`Ssss！\n08-05`） | 采集侧取 `split('\n')[0]`；credit 用 `note_id[:8]`，别用完整 24 位 ID |
| **`〔交通〕` / `〔事项〕` 块内容凭空消失** | 抽取层自己写了一套「只认 `【】`」的 `split_blocks`，非景点块被当成前言块：要么整块丢弃（H/I 列），要么错误并进上一个景点的详细行程（D 列） | 必须 `from nonspot_rules import split_blocks`（返回带 `kind` 的三元组），D→当日注意事项、E→丢弃、H→当日备注、I→并入注意事项 |
| **`📌 当日总备注` 混进景点正文** | 它以无标记的行落在最后一个块里 | 抽取层用 `split_tail()` 切出来，再 `tail_block()` 拆成「小标题 + 正文」 |

## 五、成本与耗时参考（贵州 7 天 6 晚 / 2 人 / 自驾）

| 环节 | 实测 |
|---|---|
| 小红书原图采集 | 16 个景点；每景点 2-3 关键词 × 取 6 帖；约 12 分钟（后台跑，含限速） |
| 采集产出 | 423 张可用原图（900-1600px，176-800KB/张） |
| 挑图 | contact sheet 粗筛 + 逐景点 1 张放大复核图 |
| 地图 | 15 张高德截图（审图号完整） |
| 出产物 | 阶段一（封面+总篇章+DAY1）HTML 43KB / PDF 12 页 / PPT 10 页 |
