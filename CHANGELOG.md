# Changelog

本仓库所有值得记录的变更。

## [2026-09-12] · 地图四级降级 + PDF 改为用户自行打印 + README 补 key 申请

同样出自青甘大环线项目复盘，以下是用户确定的**长期约定**（不是一次性偏好）。

### 🗺️ 变更：景点地图改为四级优先级降级

原先的逻辑是「有 key 就用高德 API」，等于把最清楚的一档当成了首选。但地图上画不出
游览顺序、机位、里程 —— 博主手绘导览图的信息量是 API 给不了的。现改为：

| 优先级 | 来源 | 降级条件 |
|---|---|---|
| ① 最高 | 小红书搜到的大景点地图（手绘导览图 / 导览牌实拍） | 默认首选，**但必须先过甄别** |
| ② 次高 | 天地图网页截图 | ① 找不到，或甄别不通过 |
| ③ 低 | 高德 Web 服务静态地图（用户自备 key） | 需要 marker 点位 / 零 UI 残留 / `scale=2` 高清 |
| ④ 最低 | 其它保底（景区官网导览图等） | ①②③ 全拿不到 |

**① 的甄别是硬要求**，也是最容易出错的地方：**搜索关键词命中 ≠ 这张图属于这个景点**
（实测「翡翠湖」会命中安徽的同名公园）。四项全过才采用 ——
图上有可读地名、帖文语境确实指向该景点、相对位置合常识、且不是多景点拼贴合集。
任一项不过就降级（配错景点的地图比没有地图更糟）。

配套新增 **`scripts/map_sources.py`**，把「优先级」从文档约束变成可执行校验：

- `--init` 扫描 `assets/maps/*.png` 生成 `_sources.json` 骨架
- `--set <slug> <source> [credit] [--verified]` 登记来源（`xhs` / `tianditu` / `amap` / `other`）
- `--check` 校验：未登记、xhs 未标 `verified`、保底缺出处 → FAIL，退出码 1
- `--caption <slug>` 按来源生成统一图注，避免正文手写时把来源标错

四个分支（未登记 / xhs 未甄别 / 保底无出处 / 来源名非法）均已实测；
青甘项目 19 张高德图登记后 `--check` 为 **FAIL 0 / WARN 0**。

### 🚫 变更：PDF 永久不再自动生成

用户明确要求：**不要调用 `roadbook_print_pdf.py` 自动出 PDF**，改为交付 HTML + 打印步骤，
由用户自己 `Ctrl+P` 另存为 PDF。理由很直接 —— 自动打印这条链路反复带来版式漂移
（空白页、背景色丢失），而浏览器原生打印所见即所得，还省一次全页面渲染。

已固化进文档的打印配置（照用户的实际截图）：

| 打印项 | 取值 |
|---|---|
| 目标打印机 | 另存为 PDF |
| 页面 / 布局 / 纸张 | 全部 / 纵向 / A4 |
| 每版打印页数 | 1 |
| 边距 / 缩放 | 默认 |
| 选项 | ☑ 页眉和页脚　**☑ 背景图形** |

> **「背景图形」必须勾上**，否则暖色底纹与卡片配色全部丢失，出来是一张白底黑字。

同步清理了四处表述：SKILL.md 的数据流 / 共用脚本 / 交付清单 / 硬约束，
roadbook.md 的执行顺序（删掉两处 `roadbook_print_pdf.py`）/ 硬约束 2 / 成本参考表。
**`roadbook_print_pdf.py` 保留在仓库里但标注弃用**，唯一保留的是打印 CSS 的
`break-inside:avoid`（那是用户打印时唯一还需要我们兜住的地方）。

### 🗑️ 后续：PDF 脚本彻底删除（同日，用户进一步要求）

标注「弃用」还不够 —— **只要文件还在，下一次看到它的人（或 AI）就会顺手再跑一次**。
所以 `roadbook_print_pdf.py` 已从技能目录与 GitHub 仓库**一并删除**（本地 + 远程），
为此同步清理的引用点：

- `SKILL.md`：第二阶段的脚本链、交付清单、两条硬约束 → 改为「脚本已删除，不要临时重写一个」
- `references/roadbook.md`：数据流图删掉 `--▶ 路书.pdf` 分支改成「用户 Ctrl+P」、
  章节标题改为「HTML / PPT」、硬约束 2、踩坑表末行
- `README.md`：`scripts/` 表格里「PDF printer is retained but deprecated」→ **removed**
- 全盘扫描确认：本地技能目录与仓库内**已无任何 `*pdf*` 脚本**

> 注：该脚本仍存在于 2026-09-11 之前的 git 历史中。要让它在历史里也消失需要
> `filter-branch` 重写历史 —— 除非有泄漏风险，一般不必做，删掉 HEAD 已能让链路失效。

**打印 CSS 同日稍晚也删了**（用户实测 `break-inside:avoid` 挡不住浏览器打印分页，
卡片照样被切 —— 无效代码）：`@media print` 整块 + 贵州 `.fig-map/.ph` 里当年 v2 修复的
`page-break-inside/break-inside` 属性，共清理 6 个文件（技能模板、青甘模板与成品 HTML、
贵州模板与两份成品 HTML）。「PDF 相关约束」就此清零，上面第 56-57 行那句「唯一保留」
随之作废。

### 📝 README：新增高德 Web 服务 key 的申请步骤

此前只在 playbook 里讲了 API 用法，没说 key 从哪来。现补全：

注册 <https://console.amap.com> → 创建应用 → **服务平台必须选 `Web服务`**
（选 `Web端/JS API` 会以同样的 `UNKNOWN_ERROR 20003` 失败，是最高频的配错）→
取 32 位 key → **用环境变量 `AMAP_WEB_KEY` 传入，绝不硬编码**。
同时把 README 里三处「PDF 是交付物」的表述改掉，并更新 Latest 条目。

### 🔒 安全

同步前对两个技能目录做敏感扫描（token / 私钥 / 邮箱 / 本机路径）：**0 命中**。
用户的高德 key **从未写入任何被推送的文件** —— 只存在于本地项目脚本
（`青甘大环线_v3/roadbook/collect_maps_amap.py`，且已加「勿连同 key 分享」警告并支持
环境变量覆盖）；技能文档与 README 只写「从环境变量读」，不含任何 key 片段。

## [2026-09-11] · 修复 `〔交通〕/〔事项〕` 块静默丢内容 + 登录判据纠正

本次修复全部来自**青甘大环线 9 天 8 晚自驾路书**实战（9 天行程 / 18 个景点 / 194 张实拍图），
每条都有实测复现与回读验证。

### 🐛 修复：`roadbook_extract_content.py` 会把非景点块的内容静默丢掉

**症状**：行程表里按技能约定写的是 `〔交通〕兰州·中川机场`、`〔交通〕西宁取车`，
但生成的路书里这些内容凭空消失 —— **不报错、不告警**，只是没有。

**根因**：该脚本自带一套「只认 `【】`」的 `split_blocks`，于是：

| 列 | 旧行为 | 后果 |
|---|---|---|
| D 列 | `〔交通〕` 块被当成「前言块」并进上一个景点 | 机场流程跑到景点正文里 |
| H 列 | `name=None` 被 `if n:` 跳过 | 穿搭与避坑整块丢失 |
| I 列 | 同上 | 注意事项整块丢失 |
| E 列 | 前言块与景点块混在一起 | 机场也长出「机位」 |

而技能文档明确要求「HTML 链路与 PPT 链路必须引用同一份 `nonspot_rules`」——
本文件恰恰没有引用。

**修法**：旧实现改名 `legacy_split_blocks` 并标注废弃（不再遮蔽 import），
改用 `from nonspot_rules import split_blocks, clean_items, KIND_ICON`，按 `kind` 分流：

- `D` → 景点建块；`transit`/`chore`/前言 → 当日注意事项（🚉/🛍 节点名起小标题）
- `E` → 景点块挂景点；前言作日级机位；**非景点块整块丢弃**
- `H` → 景点块挂景点；非景点块 → 当日备注
- `I` → 景点块挂景点；其余并入当日注意事项

同时补 `split_tail()` / `tail_block()`：把误落在最后一个块尾部的
`📌 当日总备注 / 总注意事项` 切出来，避免与景点正文混在一起。

另新增 `refine_kind()`：`【敦煌抵达提示】`「【返程托运提醒】」这类**名字里带
「提示 / 提醒 / 说明 / 须知 / 注意」**的 `【】` 块其实不是景点，
默认判定会把它们当大景点，现降级为事务节点。

**验证**（用 9 天真实行程表逐日回读）：DAY1 从「只有景点、注意事项为空」变为
「1 个景点 + 当日备注 3 条 + 当日注意事项 5 条」，机场 / 取车内容完整归位；
全 9 天「伪景点块」残留 0。

### 🐛 修复：`xhs_collect_photos.py` 采到的作者名混进发布日期

卡片 `.author` 的 `innerText` 实际是「作者名 + 换行 + 日期」，直接落盘后路书 credit
会显示成两行（`@Ssss！` / `08-05`）。修法：`split('\n')[0].trim()`；
已有数据可一次性后处理洗掉。

### 🔧 改进：`html_screenshot.py` 不再往技能目录里写产物

原输出目录写死为 `技能目录/roadbook/_raw/shots`，等于每次截图都往技能里塞文件
（技能目录应保持只读）。改为默认取 **HTML 同级目录的 `_raw/shots`**（路书工程约定），
并支持 `--out <目录>` 显式指定；同时修正 `--out` 的值被误当成位置参数的问题。

### 📝 文档：`xhs-humanized-collect` 登录判据自相矛盾 + 新增踩坑⑫

原文档一处写「唯一可靠判据是 `.login-btn` 不可见」，另一处写「唯一可靠判据是
`id_token` 存在」—— 两者冲突，且后者**是错的**。

**实测**：复用一份 3 周前的 profile，cookie 看起来完全正常
（`id_token` 长度 136 + `web_session` + `a1` + `unread` 都在），
但打开首页**已经弹出扫码框、登录按钮可见** —— 登录态早就过期，`id_token` 只是残留。
只用 cookie 判断会在采集启动时静默通过、跑到中途才开始报错。

已统一为：**主判据「登录按钮不可见」+ 辅助「`page.screenshot()` 目视复核」**，
实测过程记为踩坑⑫。

### 📝 文档：`references/roadbook.md` 踩坑表补 5 条

- **景点卡不出图且不报错** —— `SPOT_RULES` 没配 → `slug=None` → `resolve_photos()` 直接返回 `[]`，
  日志毫无异常。首次构建必须跑 `--stage 1` 确认目标景点「图 N」不为 0。
- **挑图挑到博主封面** —— 每篇 `01.jpg` 是封面（多大字标题 / 拼贴），从 `02.jpg` 起挑，
  先出 contact sheet 粗筛再定 `PICKS`。
- **credit 显示两行** —— 同上面的作者名问题；`note_id` 用前 8 位即可。
- **`〔交通〕` / `〔事项〕` 内容凭空消失** —— 必须 `from nonspot_rules import split_blocks`。
- **`📌 当日总备注` 混进景点正文** —— 用 `split_tail()` 切出来。

### 📝 文档：补上 `roadbook.md` 指向却**并不存在**的「地图截图」章节

`roadbook.md` 一直写着「截图的可行手法与坑见 `scraping-playbook.md` 的『高德地图截图』一节」，
但该章节**从未存在**（playbook 里只有价格抓取五节）。本次青甘项目实测后补全为
「六、地图截图」，结论与原先的预期相反：

- **高德网页版已经不可用**：`amap.com/search?query=...` 与坐标直连 URL 都弹登录框
  （短信 / 二维码），关掉后立刻升级为滑块验证。自动化解滑块既不可靠也属对抗行为，直接放弃。
- **天地图可行**：`map.tianditu.gov.cn` 免登录，底部常驻 `审图号 GS（2025）1508 号`，
  满足「必须保留审图号」的硬约束。已落成 `collect_maps.py`（三级点选 + 浮层清理 + 边缘裁切）。
- 三条最容易踩的：**必须逐字 `type()` 而非 `fill()`**（后者常不触发前端事件，
  搜索框有字但结果面板不刷新，看着像「搜了个寂寞」）、**成功判据看地图中心坐标**
  （天地图默认视野恒为 `104.20,33.56`，可直接写进断言）、
  **裁掉 UI 三边但务必保留底部审图号**。
- 同时修正本节内另一处与 SKILL.md 冲突的登录判据（原写「必须用 `id_token` 存在」）。

### 🐛 修复：`html_screenshot.py` 截出来的实拍图成片空白

**症状**：5.5 万 px 长的路书页面，截图里景点卡的「实拍参考」网格**整片空白**，
看着像配图丢了 —— 但文件全在（113 张逐张 `Image.verify()` 通过、HTML 引用 0 缺失）。

**根因**：`<img loading="lazy">` + 脚本只做「跳到底 → 回顶」。中间区域的图片
**从未进入过视口**，因此压根没发起请求。这个坑在 `roadbook.md` 的 PDF 打印一节
已记录过（「实拍参考网格 / 地图全空」），但截图脚本没有同步修。

**修法**：逐屏滚动（每 700px 停 120ms）触发懒加载 → 回顶 →
把仍未加载的 `loading` 改成 `eager` 兜底 → `wait_for_function` 等全部
`complete && naturalWidth > 0`。

### 📝 文档：`scraping-playbook.md` 补「高德 Web 服务静态地图」

有 Web 服务 key 时静态地图 API 是**最优解**：无 UI 残留、支持 marker 标注与 paths 折线、
`scale=2` 高清，且**图片自带版权与审图号水印**（实测 `GS(2018)1729号`）—— 合规无需额外处理。

记录四个必踩的坑，前三个都返回同一个毫无指向性的 `UNKNOWN_ERROR 20003`：

- `size` 必须写**星号** `1024*600`，写成 `1024x600` 直接报错
- marker 的 `label` **只能单字符**（单字「宁」「A」正常，写「西宁市区」必错）
- 密集调用会限流：先能出图，几轮后**全部**报错，换任何参数都没用 → 3s 间隔 + 退避重试
- **别把限流当参数错**：反复改参数只会把封禁拖更久；正确做法是先发一次「最简请求」做对照，
  简单请求能过就说明 key 没坏

同时写明地图图源的优先后序：**高德 Web 服务 API（有 key）→ 天地图网页截图（无 key）
→ 小红书博主手绘 / 导览图**，三者都要保留审图号或来源标注。

### 🔒 安全

- 同步前扫描两个技能目录：无 token / 密钥 / 邮箱 / 私钥 / 本机路径；仅 `SKILL.md` 的
  2 处「禁止这样做」示例含 `AppData\Local`，且用 `<u>` 占位符，不含真实用户名。
- 本次同步按 **LF 归一化**，仓库里 27 个仅行尾不同的文件未被误改，diff 只含真实修复。

## [2026-09-10] · 图文路书链路 + 海报版 PPT + 新增 xhs-humanized-collect 技能

### ✨ 新增：`travel-guide-builder` 图文路书（HTML / PDF / 单文件版）

原先只有 xlsx 行程表，现在补齐了**能直接打印带走**的图文路书链路：

| 文件 | 作用 |
|---|---|
| `references/roadbook.md` | 路书章节：内容结构、模板变量、渲染与打印全流程 |
| `templates/roadbook.html.j2` | 路书 Jinja2 模板（暖色调棕金 + 米白） |
| `scripts/roadbook_extract_content.py` | 从 xlsx / content.json 抽取路书内容 |
| `scripts/roadbook_build_html.py` | 渲染 HTML（含地图图源替换） |
| `scripts/roadbook_build_ppt.py` | 生成 PPT |
| `scripts/roadbook_inline_html.py` | 图片转 base64 内嵌 → 单文件 HTML |
| `scripts/roadbook_print_pdf.py` | Playwright 打印 PDF |

配套脚本：`html_screenshot.py`、`ppt_layout_check.py`、`xhs_collect_photos.py`、
`xhs_list_picks.py`、`xhs_make_contact.py`、`xhs_review_picks.py`。

### ✨ 新增：海报版 PPT（16:9，1920×1080）

按横向信息图海报风格重做：蓝色笔刷标题带 + 金色左侧概览栏 + 编号卡片 + 底部时间轴。
与普通 PPT 并存，互不覆盖（`贵州7天6晚自驾路书_海报版.pptx`）。

### 🔄 变更：地图图源默认改为小红书

- 景点地图**优先用小红书实测手绘 / 导览图**（`assets/maps_xhs/`），高德仅作兜底。
- `roadbook_build_html.py` 增加 post-render 替换：`assets/maps/<slug>.png` → `assets/maps_xhs/<slug>.png`，
  缺文件才回落到原高德图，**旧文件保留可一键回滚**。

### 🐛 修复：PDF 打印出大片空白页（三层根因）

这是本次最折腾的坑，按发现顺序记录：

| 层 | 症状 | 根因 | 修法 |
|---|---|---|---|
| 1 | 实拍参考网格 / 地图全空 | `<img loading="lazy">` 打印时还没请求 | 打印前 `im.loading='eager'` + 滚一遍全文档 + 等全部 `complete && naturalWidth>0` |
| 2 | 容器被分页拦腰截断 | `.fig-map` / `.ph` 缺 `page-break-inside:avoid` | CSS 补 `page-break-inside:avoid; break-inside:avoid` |
| 3 | 整页全白（真凶） | 地图是 720×1600 竖版，`width:100%` 渲染出 1111px > A4 可用 803px，引擎把图推到下一页 | `.fig-map img{max-height:240mm; object-fit:contain}` |

效果：**58 页 → 54 页，完全空白页 0 张**（按「无图且无文字」自动扫描判定）。

> 结论：路书类长文档打印 PDF，**必须**加一道空白页扫描再交付，肉眼翻页很容易漏。

### ✨ 新增技能：`xhs-humanized-collect`

小红书拟人化采集技能，作为并列 skill 合入本仓库。核心内容：

- **踩坑⑨（最高危）**：绝对禁止把自动化浏览器指向真实浏览器 profile 目录。
  Chrome App-Bound Encryption 会判定启动上下文不可信并**原地删除真实 profile 的 Cookie**
  （实测销毁 1661 条，含 Google 账号登录态，不可恢复）。这是唯一「会毁用户数据」的坑。
- **踩坑⑩**：搜索结果页 `/search_result?keyword=...` 会**多跳重定向**
  （`/search_result/` → `/search_result?type=51` → captcha 或结果）。
  在重定向窗口内调 `page.evaluate` 会抛 `ExecutionContext was destroyed`，
  **极易被误判为账号被风控**而白白等待冷却。
  修法：把 `evaluate` 包成 14 轮 × ~3s 重试循环，并检测 captcha URL 立即中断。
- 取图必须走 `__INITIAL_STATE__.note.noteDetailMap[].note.imageList[].urlDefault`
  （用 `.swiper-slide img` 只会抓到 48×48 表情贴纸）。
- 直访笔记必须带 `xsec_token`，裸 `/explore/<id>` 会 404。
- 采集落盘时保存**完整 href（含 xsec_token）**，后续回访无需再走搜索接口，
  从根上减少对账号的请求次数。

### 🔒 安全

- 清掉两处硬编码的 Windows 绝对路径（`C:\Users\<用户名>\...`），改为运行时动态发现
  （环境变量 → 向上查找 `.workbuddy/xhs_qr_profile` → 兜底 `~/.workbuddy/`）。
  既避免泄露用户名，也让脚本在别人机器上能跑。
- 推送前扫描：无 token / 无邮箱 / 无 Cookie 库引用 / 无本机路径残留。

## [2026-09-08] · 初版

- `travel-guide-builder` 技能：按模板生成多 sheet 行程攻略 xlsx（全部行程 / 人均预算 /
  费用明细 / 物品清单 / 景点地图），含九列填充规则与真实抓价 playbook。
