# Changelog

本仓库所有值得记录的变更。

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
