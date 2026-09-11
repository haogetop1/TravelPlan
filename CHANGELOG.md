# Changelog

本仓库所有值得记录的变更。

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
