# TravelPlan — agent 通用入口（AGENTS.md）

> **这是给「任何 agent 平台」的入口文件。** Codex CLI、Cursor、Gemini CLI、Windsurf、
> Zed / Amp / Jules 等都读 `AGENTS.md`；Claude Code 另有 `CLAUDE.md`；
> WorkBuddy / CodeBuddy 直接读技能里的 `SKILL.md`。
>
> 权威说明在各技能内：`travel-guide-builder/SKILL.md`、`xhs-humanized-collect/SKILL.md`、
> `travel-guide-builder/references/scraping-playbook.md`（抓取实操与坑）。
> 本文件只做**索引 + 硬约束**，避免规则被漏读。

---

## 一、这是什么

两个可组合的技能，用来生成**行程攻略表格**与**图文路书**：

| 技能 | 作用 |
|---|---|
| [`travel-guide-builder/`](travel-guide-builder/) | 按用户**自有的表格模板**生成多 sheet 行程攻略 `.xlsx`（全部行程 / 人均预算 / 费用明细 / 物品清单 / 景点地图），再产出**图文路书 HTML** 与 **PPT** |
| [`xhs-humanized-collect/`](xhs-humanized-collect/) | 拟人化浏览器采集（小红书 / 携程酒店 / 神州租车等）：持久登录态、常驻会话、真人节奏与限速 |

数据来源以**小红书实测帖**为第一优先，其次携程（酒店/机票/租车）、神州租车官方页。

---

## 二、怎么装

```bat
py -3 install.py --list                  :: 看支持哪些宿主、本机装了哪些
py -3 install.py --target auto           :: 装到本机检测到的全部宿主
py -3 install.py --target claude         :: 只装某一个
py -3 install.py --list                  :: 查看后按提示操作
py -3 install.py --target cursor --project D:\my-trip --dry-run
```

安装器会：① 把两个技能复制到宿主平台的技能目录；② 给不认 `SKILL.md` 的平台
生成对应入口文件（`AGENTS.md` / `GEMINI.md` / `.cursor/rules/*.mdc` / `.windsurf/rules/*.md`）。
**不覆盖**已存在的技能目录（要覆盖加 `--force`），**不覆盖**非本工具生成的入口文件。

不装也能用：直接在**本仓库目录**里跑脚本即可（两个技能互为兄弟目录，
脚本会在多个候选位置里自动找彼此，见 `xhs-humanized-collect/scripts/platform_compat.py`）。

### 环境要求（Windows）

```bat
py -3 -m pip install openpyxl python-pptx playwright pillow jinja2
playwright install chromium
```

- **需要原生 Chrome**（抓取必须用它）。Playwright 自带 Chromium 会被携程 / 神州的
  指纹风控直接拦（页面只显示 `whaleguard block`）。可用 `CHROME_PATH` 指定路径。
- 高德静态地图需要用户**自备** Web 服务 key，只走 `AMAP_WEB_KEY` 环境变量，不得入库。

---

## 三、标准工作流

```bat
:: ① 组装内容 → 生成 xlsx
py -3 travel-guide-builder\scripts\build_guide_xlsx.py content.json "旅程攻略.xlsx"

:: ② 抽内容 → 出图文路书（先 --stage 1 只出封面+总篇章+DAY1，让用户确认版式）
py -3 travel-guide-builder\scripts\roadbook_extract_content.py
py -3 travel-guide-builder\scripts\roadbook_build_html.py --stage 1

:: ③ 分段截图验收排版
py -3 travel-guide-builder\scripts\html_screenshot.py "路书.html" 6

:: ④ PPT（详细版 / 简洁版两套）
py -3 travel-guide-builder\scripts\extract_xlsx_slides.py
py -3 travel-guide-builder\scripts\build_ppt_detail.py --stage 1
```

**交付节奏**：先小步（路书 `--stage 1`、PPT `--stage 1`）让用户确认版式，确认后再全量。

---

## 四、硬约束（用户明确定过，**不要自行改**）

1. **PDF 一律不自动生成。** 只交付 HTML + 「另存为 PDF」的打印步骤
   （A4 / 纵向 / 每版 1 页 / 边距缩放默认 / ☑ 页眉和页脚 / **☑ 背景图形**）。
   不要临时写 HTML→PDF 脚本，也不要顺手多做一个 PDF。
2. **地图四级优先级**（依据是信息价值，不是画质）：
   ① 小红书搜到的大景点导览图 —— **必须先甄别**（图上有可读地名 / 帖文语境确实指向该景点 /
   相对位置合常识 / 非多景点拼贴），任一项不过就降级，**配错景点的地图比没有地图更糟**
   → ② 天地图 → ③ 高德 Web 服务静态地图（需自备 key）→ ④ 其它保底。
   每张地图的图注都要写来源与审图号。
3. **所有平台抓取走常驻会话，登录一次。** 起有头浏览器 + CDP 端口，采集脚本 attach，
   **结束只关标签页、绝不关浏览器**；登录态用 `human_act.save_cookies/restore_cookies`
   落盘快照（含会话级 cookie）。
   > 注意：在受沙箱保护的环境里 agent 自己拉起的浏览器活不过一条命令
   > （`DETACHED_PROCESS` / `CREATE_BREAKAWAY_FROM_JOB` / `cmd start` / 计划任务
   > 四种实测全部被回收）。需要用户手点登录时，让**用户自己**启动窗口。
4. **只读价，绝不下单。** 走到「确认订单」页读全额为止；脚本内置禁区词表
   （确认订单 / 提交订单 / 去支付…）。撞到验证码或滑块**立即中止并告知用户**，不硬试。
5. **xlsx 冻结窗格**：`全部行程` = 首行 + A、B 列（`C2`）；`费用明细` = 只冻结首行（`A2`）；
   人均预算 / 物品清单 / 景点地图 = **不冻结**。
6. **富文本默认开启**：`【景点】` 红加粗、`〔交通〕/〔事项〕` 棕加粗，所有 sheet 生效。
   回读校验必须 `load_workbook(path, rich_text=True)`，否则会误判「没生效」。
7. **预算双口径**：出行区间覆盖国家法定节假日时，**必须**给「普通日 vs 节假日」双预算
   并标涨幅倍数（机票/酒店/租车分项同理）；纯普通日给单价并注明「非节假日口径」。

---

## 五、跨平台通用的坑（都是实测踩出来的）

| 坑 | 后果 | 正确做法 |
|---|---|---|
| 中文 Windows 的 `tasklist`/`taskkill` 输出是 GBK，用 `subprocess(text=True)` | reader 线程抛 `UnicodeDecodeError` 被吞 → 「进程活着却判成已死」 | 按字节读回，再自行解码（`platform_compat.run_bytes`） |
| 给用户双击的 `.bat` 写了中文 | `cmd.exe` 按 GBK 解析 UTF-8 → 满屏乱码，`chcp 65001` 救不回来 | `.bat` 内容**纯 ASCII + CRLF**，或直接给「Win+R 一行命令」 |
| 用 `innerText` 读页面 | `content-visibility` 折叠区被跳过 → 按文本找元素永远找不到 | 遍历文本节点（`human_act.deep_text`） |
| 按精确文本找按钮 | 前端用空格做字间距（「确 认」）→ 匹配恒为 0 候选 | 匹配前先归一化空白 |
| 逗号拼接多个 CSS 选择器 | 那是**并集**，`.first` 按 DOM 顺序取 → 点错元素 | 用选择器**优先级列表**逐个试 |
| 桌面宽度打开移动端 H5 | 布局错位（卡片被塞进内部滚动容器、被吸顶条遮挡） | CDP `Emulation.setDeviceMetricsOverride` 模拟手机视口 |
| 元素「看得见点不动」（`intercepts pointer events`） | Playwright 的 `.click()` 可点性检查不过 | 用 `bounding_box` 取坐标后 `page.mouse.click(x, y)` 走完整事件链 |
| 按钮点了没反应但也没报错 | 可能是缺登录态 / 定位授权 / 前置必填项 | 先补齐前置条件，再判断「点不动」 |
| 输入框里中文字符写了两遍 | `Keyboard.type()` 对非 ASCII 走 `insertText`，站点又在 `keydown` 里插一次 | 用 `insert_text` + 回读校验（`human_act.human_type`） |
| 一个平台抓不到就断言「站点取消了网页版」 | 误判产品行为，白费排查 | 先确认是否缺登录态 / 授权 / 路由 |

---

## 六、给 agent 的指令模板

> 用 travel-guide-builder 技能，按我给的模板生成【青海甘肃大环线】【9 天 8 晚】【自驾】攻略，
> 旅行时间 2027/7/17-7/25，8 人（4 男 4 女），深圳出发，飞机往返兰州。
> **先生成 xlsx，其它文件先不生成。**

用户偏好（跨项目约定）：

- 中文输出；正文零 emoji 点缀、暖色调（`#b08968` 棕金 + `#faf7f2` 米白）、677px 标准微信宽度
- 先出小样确认版式，再全量
- 不愿被反复要求重新登录 / 扫码
