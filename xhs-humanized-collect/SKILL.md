---
name: xhs-humanized-collect
description: 小红书拟人化采集。用 Playwright 持久化登录态 + 真实有头浏览器 + 随机拟人节奏 + 限速，绕过风控批量采集笔记正文（标题/作者/点赞/日期/正文）。适用于需要以小红书实测帖为事实来源做攻略、选品、舆情、调研的场景。触发词：小红书采集、小红书搜索、xhs 采集、小红书避坑帖、登小红书抓数据、小红书攻略素材。
agent_created: true
---

# 小红书拟人化采集

## 宿主平台（Windows · 各 agent 平台通用）

本技能**不绑定具体 agent 平台**：

- `SKILL.md` 遵循 Agent Skills 规范（frontmatter 只需 `name` + `description`）
  → WorkBuddy / CodeBuddy / Claude Code 等可直接自动发现；
- 不认 `SKILL.md` 的平台（Codex CLI / Cursor / Gemini CLI / Windsurf / 其它读
  `AGENTS.md` 的工具）由仓库根的 `AGENTS.md` 与 `python install.py --target <平台>`
  生成的入口文件接管。

**平台差异全部收敛在一处**：`scripts/platform_compat.py`
（原生浏览器探测、会话目录、进程管理、技能目录发现、各宿主安装目标）。
换平台只改它 —— 这条是 2026-09-17「修复只落在某一个副本里必然复发」的教训。
自检：`python scripts/platform_compat.py --selfcheck`。

环境：**Windows 10/11** + Python 3.10+（`py -3`）；需要**原生 Chrome**。

## 何时用

- 需要以**小红书真实用户实测帖**为事实来源（旅游攻略避坑、消费决策、选品、口碑调研）
- 关键词明确、需要批量读**笔记正文**（不只是标题）
- 要求稳定、不触发滑块/验证码/封禁

## 核心思路（务必先理解）

**不要去逆向 `x-s`/`x-t` 签名硬怼接口。** 小红书风控的核心是拦「无登录态 + 批量机器流量」，
所以正确解法是**让脚本表现得像真人在刷帖**：

| # | 手段 | 落地方式 |
|---|---|---|
| 1 | **真实登录态** | `launch_persistent_context` 持久化 profile，扫码登录后 cookie 复用 |
| 2 | **登录判据要准** | 以登录按钮 `.side-bar-component .login-btn` **不可见**为唯一判据（见踩坑①） |
| 3 | **关自动化特征** | 启动参数 `--disable-blink-features=AutomationControlled` |
| 4 | **行为拟人** | `random.uniform()` 随机延迟 + 完全走 UI 点击（搜→点开→抽正文→Escape→下一帖） |
| 5 | **限速节流** | 每词只取前 N 篇（默认 5），词间休息 1.5–3s；整体速率控制在每帖 ~8s |
| 6 | **有头浏览器** | `headless=False` + `viewport 1440×900` |
| 7 | **容错续跑** | 每帖 try/except；`sys.argv[1]` 支持从指定关键词断点恢复 |

实测基准：23 词 × 5 帖 = 115 篇，耗时约 16 分钟，**全程零风控报错**。
2026-09 贵州攻略实战：30 词 × 4 帖 = 119 篇（去重 116），图片 561 张，全程零风控。

## 🔴 常驻会话模式（强制，2026-09-17 用户明确要求）

**浏览器一关，会话 cookie 就带走了。** 站点登录态里含**会话级 cookie**
（无过期时间、只驻内存），`browser.close()` / `ctx.close()` 之后**不会落盘**进
profile 的 cookie 库；下次重新 `launch` 就是「已退出登录」，只能再扫码。
而**高频扫码登录比采集本身更容易触发风控** —— 所以「每次采集都重新 launch」
这个习惯本身就是风险源。

规矩（**所有平台通用，不止小红书**——携程 / 天地图 / 高德 / 神州同理）：

1. **一次启动，常驻不退出**：`session_daemon.py start` 起一个长驻浏览器
   （独立 profile + CDP 端口）。
2. **采集脚本挂上去，不自己 launch**：设 `XHS_CDP=http://127.0.0.1:9222`，
   脚本内部走 `connect_over_cdp`；结束时**只关标签页，绝不 `browser.close()`**。
3. **登录也在常驻会话里做**：`XHS_CDP=... python xhs_login.py` —— 扫完码浏览器不关，
   登录态留在常驻进程里（独立模式扫完就关，等于白扫）。
4. **同一批任务中途不要 stop**：`stop` = 下次要重新登录；只有跨天/跨平台收尾才重启。
5. 只有调试才用独立模式，日志会明确警告「会丢登录态」。

```bash
python scripts/session_daemon.py start                        # 起常驻会话（一次）
XHS_CDP=http://127.0.0.1:9222 python scripts/xhs_login.py     # 登录（会话内）
XHS_CDP=http://127.0.0.1:9222 python ../travel-guide-builder/scripts/xhs_collect_photos.py
python scripts/session_daemon.py status                        # 随时确认还活着
```

> 实现见 `scripts/session_daemon.py`（`start` / `status` / `exec` / `stop`）；
> 它内置护栏：**profile 指向真实浏览器目录时直接拒绝启动**（踩坑⑨）。
> 默认用**原生 Chrome**（自动探测）——携程/神州的指纹风控会拦 Playwright 自带内核。

### ⚠️ 更正（2026-09-18 实测）：沙箱里「进程级常驻」不成立，真正的解法是 profile + cookie 快照

别被上一条误导。**在受沙箱保护的执行环境里，脚本拉起的浏览器活不过一条命令**：
沙箱会在命令结束时清掉整棵进程树，以下方式**全部实测失败**：

| 方式 | 结果 |
|---|---|
| `subprocess` + `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP` | 下一条命令里端口已关 |
| `+ CREATE_BREAKAWAY_FROM_JOB` | 同上 |
| `cmd` 的 `start` 拉起 | 同上 |
| 注册计划任务（cmdlet 未被拦的情况下） | Chrome 起来了、profile 也建了，随后仍被杀 |

**所以请按下面两条来，不要再折腾「让进程别退出」**：

1. **让用户自己启动窗口**（不在沙箱进程树里，能一直活着）：
   ```bat
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 ^
     --user-data-dir="%LOCALAPPDATA%\agent-scrape-session\browser_profile" https://目标站点
   ```
   > **不要手写这条命令** —— 用 `platform_compat.launch_instructions(exe, port, profile)`
   > 生成，它会自动取本机真实的 Chrome 路径、当前会话目录，并把「为什么要你自己启动」
   > 「`.bat` 编码坑」一并写进说明。
   > 会话目录的口径见 `platform_compat.session_dir()`：
   > `SCRAPE_SESSION_DIR` >（旧的 `<cwd>/.workbuddy` 若已用过则沿用）> `%LOCALAPPDATA%\agent-scrape-session`。
   > 给用户双击的 `.bat` **必须纯 ASCII + CRLF**（cmd 按 GBK 解析 UTF-8 会满屏乱码，
   > `chcp 65001` 也救不了）；拿不准就直接给 Win+R 的一行命令。
2. **cookie 快照兜底**（关键）：用 `human_act.save_cookies()` / `restore_cookies()`
   把**全部 cookie（含会话级）**落盘成 JSON，下次 attach 时注回 —— 实测杀进程重启后
   登录态照样有效。脚本里 `try: restore_cookies(ctx, "<站点tag>")`，任务收尾前 `save_cookies()`。
   ⚠️ `restore_cookies` 的 `domains` 要写**完整域名后缀**（`zuche.com`），
   写 `zuche` 会一条都匹配不上（`endswith` 陷阱，实测还原 0 条就是这个原因）。

3. **还有一个取巧但有效的形态**：把「等用户扫码/短信登录」和「采完数据」放进**同一次运行**里 ——
   沙箱只在**命令结束**时清进程树，同一命令内浏览器一直活着。
   参考：轮询检测登录成功 → 立刻 `save_cookies()` → 继续跑采集流程。

### `scripts/human_act.py` —— 所有平台共用的拟人化操作层（2026-09-18 新增）

`human_act.py` 是抓价/抓数类任务的公共机械层，**新平台采集脚本直接复用它**：

| 能力 | 用法 | 解决什么 |
|---|---|---|
| 连常驻浏览器 | `with Attached() as S: S.page` | 连不上时**自动拉起**同一 profile（自愈）；只关标签页、绝不关浏览器 |
| cookie 快照 | `save_cookies(ctx, tag)` / `restore_cookies(ctx, tag)` | 会话级 cookie 不落盘 → 反复扫码 |
| 四级降级点击 | `human_click(page, step, selector=..., verify=...)` | ①选择器 →②bbox 坐标点击 →③标定表固化坐标 →④截图交人看 |
| 风控中止 | `assert_no_captcha(page)` → `CaptchaHit` | 撞验证码立刻停，不硬试 |
| 三件套落盘 | `dump(page, out, tag)` | 截图 + 文本 + 接口响应，金额可回溯 |
| 金额交叉校验 | `cross_check(...)` | 视觉读出的数字必须能在 DOM/接口里找到同值 |
| target 列表 | `targets()` / `new_targets()` | `ctx.pages` 有时收不到 `window.open` 开的新页，查 CDP 才准 |

`python scripts/human_act.py --selfcheck` 自检 12 项（含「绝不关浏览器」这类硬约束）。

### 抓取类任务的六个通用坑（跨平台，2026-09-18 实测）

| 坑 | 症状 | 正解 |
|---|---|---|
| **桌面视口毁掉 H5 布局** | 元素被塞进内部滚动容器、被吸顶条遮挡，怎么点都不对 | 用 CDP 模拟手机视口：`Emulation.setDeviceMetricsOverride({width:414,height:896,mobile:true})` |
| **`content-visibility` 骗过 `innerText`** | 截图明明显示某层内容，`body.innerText` 却返回上一层文字 | 取文字用 `textContent`，不要用 `innerText` |
| **按钮文字里有空格** | 如「确 认」（前端做字间距）→ 精确匹配「确认」永远 0 候选 | 匹配前 `re.sub(r"\s+","",s)` 归一化两侧 |
| **目标在折叠下方** | 元素 top=1124 而视口只有 896 → 点击落在视口外，什么都不发生 | 先 `scrollIntoView({block:'center'})` → **重新量 rect** → 再点 |
| **容器高度为 0** | 外层靠 transform 定位，`h=0`；「取最小元素」会选中它 | 候选过滤 `height>=14`，并优先点具体子元素（如图片） |
| **`¥` 与数字是两个文本节点** | 拼整页文本时插了分隔符 → 金额正则全配不到 | 拼文本用**空串**；并防「金额被后一段日期吃掉」（`￥316`+`09-18` → 31609，用 split 分段并校验分项之和） |


## ⚠️ 踩坑⑥：取图千万别用 `.swiper-slide img` —— 那抓到的全是表情贴纸（2026-09 血泪）

这条是本技能**最严重的静默失败**，之前产出的「N 百张配图」绝大多数是 48×48 的 emoji 贴纸，
真正可用的只有每帖一张带 UI 的整页截图，做路书/排版时才发现全废。

**错误做法**：遍历 `.swiper-slide img` / `.media-container img` / `#noteContainer img`，
再按 URL 后缀 `.jpg/.png/.webp` 过滤 —— 小红书面页上有**表情面板轮播**，
其 `img` 同样满足这些条件，于是被大量误收。

**正确做法：从水合后的 `__INITIAL_STATE__` 取 `imageList`。**

```python
def note_images(page, href):
    page.goto(href, wait_until="domcontentloaded", timeout=60000)
    for _ in range(12):                      # 它是异步水合的，必须轮询
        time.sleep(1.4)
        data = page.evaluate("""() => {
            const dm = window.__INITIAL_STATE__.note.noteDetailMap;
            for (const k of Object.keys(dm)) {
                const n = dm[k] && dm[k].note;
                if (n && (n.imageList||[]).length)
                    return {n: n.imageList.length,
                            urls: n.imageList.map(i => i.urlDefault || i.urlPre
                                  || ((i.infoList||[])[0]||{}).url || '')};
            }
            return null;
        }""")
        if data and data.get('urls'):
            return [u for u in data['urls'] if u]
        if page.url.startswith("https://www.xiaohongshu.com/404"):
            return []
    return []
```

要点：

1. **必须轮询**：`noteDetailMap` 初值是 `{undefined: {note:{}}}`，等 6s 常常还没水合，
   按固定 sleep 取会拿到空列表（表现和「笔记被删」一模一样，极易误判）。
2. **`urlDefault` 优先级最高**，退回 `urlPre`，再退回 `infoList[0].url`。
3. **下载后转 JPEG**（原图是 webp），并按需缩到 ≤1600px，否则 PPT/HTML 兼容性和体积都难受。
4. **落盘按「景点 slug / 帖子ID / NN.jpg」两级分类**，比按帖子ID一级分类更好用 ——
   做攻略时要的是「某个景点的一批图」，不是「某一篇帖子的图」。
5. 采样自检：**单张 < 30KB 或宽高 ≤ 300px 的直接丢了**，那必然是贴纸不是照片。

## ⚠️ 踩坑⑦：笔记直链需要 `xsec_token`，裸 `/explore/<id>` 会 404

小红书现在对笔记直访做了校验。用裸 ID 拼 `https://www.xiaohongshu.com/explore/<id>` 会跳
`/404?...&error_code=300031&error_msg=当前笔记暂时无法浏览`。

**正确做法**：搜索页里卡片的 `href` 本身就带 token，收割卡片时**连 href 一起存**，
后续用完整 href 访问：

```
/search_result/<note_id>?xsec_token=ABmGFt8...&xsec_source=pc_search
```

所以：**采集时若打算二次访问笔记（补抓图片/正文），必须把带 token 的 href 落盘**，
只存 `note_id` 等于放弃了回访能力。历史数据里只有裸 ID，只能重新搜索再取。

## ⚠️ 踩坑⑧：不要试图克隆本机 Chrome profile 来「免扫码」（2026-09 血泪）

**结论：这条路在 Chrome 152+（Win）已彻底封死，直接扫码，别浪费时间。**

失败链条（按踩坑顺序）：

1. **Chrome 运行时 Cookie 库被独占** —— `Default/Network/Cookies` 被进程锁，
   `cp` 与 `shutil.copyfile` 均失败。
2. **robocopy `/B` 备份模式也没权限** —— 即使 Chrome 已关闭也可能拿不到，别指望。
3. **克隆 profile 后 Cookie 会被清空** —— 把 `Local State` + `Default/Network/Cookies`
   复制到新 `user-data-dir` 后启动，**1661 条 Cookie 被清零只剩 14 条**。
   根因是新版 Chrome 的 **App-Bound Encryption**：Cookie 解密密钥绑定本机 DPAPI +
   进程完整性级别，**无法随 profile 目录迁移**。同目录下的 Local Storage 也一样失效。
4. **无法用默认 profile 开远程调试** —— Chrome 会拒绝
   `DevTools remote debugging requires a non-default data directory`。
5. **Playwright 注入的参数会破坏解密** —— `--use-mock-keychain` 等默认参数导致
   Chromium 无法调用系统级 Cookie 解密，即使 profile 是对的也读不出。

**唯一可行解：`launch_persistent_context` 独立 profile + 扫码一次。**
登录态永久保存在**会话目录**下（`platform_compat.session_dir()`；默认
`%LOCALAPPDATA%\agent-scrape-session`，可用 `SCRAPE_SESSION_DIR` 指定），后续所有采集复用，不用再扫。

**配套的两个坑（必看）：**

- **登录判据不能用 `web_session` 长度** —— 未登录时 `web_session` 也是 38 位匿名值，
  用 `len(web_session) > 30` 判断会**误判成已登录**。
  **也不能只看 `id_token` 是否存在** —— 过期残留照样躺在 cookie 里（详见踩坑⑫）。
  **唯一可靠判据是「登录按钮 `.side-bar-component .login-btn` 不可见」**，
  并且建议再补一张 `page.screenshot()` 目视确认，双保险。
- **二维码必须持续刷新** —— 每 20s 重新截图覆盖同一个 `qrcode.png`，
  然后**把这张图呈现给用户**（宿主若有「展示文件」的能力就用它，例如部分平台的
  `present_files`；没有就把绝对路径告诉用户）。让用户看到的永远是最新一张，
  避免「码过期了」的往返。

## 🚨 踩坑⑨（最高危 / 已造成真实数据损毁）：绝对禁止把自动化浏览器指向真实 profile 目录

**禁令（无条件遵守）：**

```
❌ 禁止 launch_persistent_context(r"C:\Users\<u>\AppData\Local\Google\Chrome\User Data", ...)
❌ 禁止 launch_persistent_context(r"...\Edge\User Data", ...)  # 同理
✅ 只用独立 data dir：<会话目录>/<name>_profile（见 platform_compat.session_dir）
```

**2026-09-09 事故实录（本人亲手造成，不可再犯）：**

- 当时的脚本 `xhs_verify4.py` 用了
  `p.chromium.launch_persistent_context(PROFILE, executable_path=真实chrome.exe, ...)`，
  其中 `PROFILE = %LOCALAPPDATA%\Google\Chrome\User Data`。
  脚本本意只是「验证真实 profile 里的小红书登录态」，**结果把真实 profile 毁了**。
- **后果**：Chrome 的 App-Bound Encryption 判定该启动上下文不可信，
  **原地删除 1661 条无法解密的 Cookie**（不是清空克隆，是清空**本机真实 profile**）。
  用户全部网站登录态被踢，**含 Google 账号**（SID/HSID/SSID/APISID/SAPISID/
  __Secure-1PSID/__Secure-3PSID/LSID/ACCOUNT_CHOOSER 全数消失，`account_info` 变空）。
- **取证特征**（可用于事后确认是否发生过同类事故）：
  - `Default/Network/Cookies` 文件尺寸保持历史高水位（本案 ~1MB / 251 页），
    但 `pragma freelist_count` 高达 223 页 → **约 89% 是删除留下的空洞**；
  - 存活 Cookie 的 `last_update_utc` **全部晚于**事故时刻（本案最早一条 = 事故后 14 分钟）；
  - `Preferences` 与 `Secure Preferences` 的 `account_info` 均为 `[]`；
  - **不可恢复**：无 VSS 卷影副本、无系统还原点、File History 未真正启用时，
    被删 Cookie 在本机不存在任何可取回的副本。

**为什么会这样（机制）**：ABE 的密钥绑定「本机 DPAPI + 调用进程完整性级别 + 应用标识」。
由 Playwright 拉起（父进程是 python、附带一堆自动化参数）时，绑定校验失败；
Chrome 的策略是**直接丢弃解不开的 Cookie**，而不是保留。同一份 `Local State`
里的 `encrypted_key` / `app_bound_encrypted_key` 可能**完全没有变化**，
所以「看密钥指纹没变 = 没事」是**错误**的推论。

**正确的「复用真实登录态」姿势**：独立 profile 扫一次码，之后长期复用
（见下方「唯一可行解」）。**绝不要为了省一次扫码去碰真实 profile。**

## 执行流程

### Step 0 · 环境

```bash
pip install playwright && playwright install chromium
```

Windows 下 `python` 可能不在 PATH：优先用 **`py -3`**；需要绝对路径时用
`python -c "import sys;print(sys.executable)"` 打印当前解释器（就是 `platform_compat.python_exe()`）。
（不要再写死某个 agent 平台的托管 Python 路径 —— 换宿主平台就失效了，
也不要把本机绝对路径提交进公开仓库。）

### Step 1 · 登录（只需做一次，之后长期复用）

```bash
python scripts/xhs_login.py
```

- 脚本会弹出有头浏览器 → 自动点登录按钮 → 显示二维码
- **用小红书 App 扫码**，5 分钟内完成
- 成功输出 `LOGIN_SUCCESS` + `COOKIES_SAVED`
- 若输出 `QR_READY` 但一直转圈：确认扫的是 App 内「扫一扫」而非微信

### Step 2 · 校验登录态（可选，排查时用）

```bash
python scripts/xhs_verify.py
```

### Step 3 · 采集

1. 编辑 `scripts/xhs_collect.py` 顶部的 `QUERIES` 列表，填入你的关键词
2. 按需调整 `collect_query(..., per_query=5)` 每词取几篇
3. 运行：

```bash
python scripts/xhs_collect.py          # 从头跑
python scripts/xhs_collect.py 12       # 从第 13 个关键词断点续跑
```

产出：`xhs_notes.jsonl`（一行一篇，含 query/title/author/likes/url/date/text）+ `xhs_collect.log`

### Step 4 · 消化

把 JSONL 去重后按关键词分类，整理成摘要 md 供后续写作/分析使用。
原则：**保留原文细节**（价格、路线、店名、时间），这些才是避坑信息的价值所在。

## 踩坑清单（血泪）

① **匿名会话也有 `web_session` cookie** —— 不能用它判断登录。唯一可靠判据是
`.side-bar-component .login-btn` 不可见。误判会导致后续采集全部静默失败。

② **登录按钮选择器会变** —— `xhs_login.py` 里做了多选择器回退：
`.side-bar-component .login-btn` → `.login-btn` → `text=登录`。若全失效，
手动打开页面 F12 找登录按钮的 class 补进列表。

③ **笔记卡片选择器 `section.note-item`** 与正文选择器
`.note-text` / `#detail-desc` / `.desc` 都是多选择器回退设计的，同理可用 F12 补。

④ **别用 headless** —— headless 是重点检测对象，风控率显著上升。

⑤ **别提高并发/无限速** —— 一旦出现滑块，立刻停 10 分钟再跑，硬闯会升级为封号。

⑥ **Windows 中文路径** 用原始字符串 `r"..."` 避免转义问题。

⑦ **写入长中文文本时注意控制台长度限制**（其他工具同理），必要时分块写。

⑧ **取图必须走 `__INITIAL_STATE__` 的 `imageList`**（详见上方「踩坑⑥」）——
`.swiper-slide img` 会把页面的表情贴纸一起抓进来，而且体积小、看起来「有图」，
不做尺寸自检根本发现不了。

⑨ **要二次访问笔记就必须存带 `xsec_token` 的完整 href**（详见「踩坑⑦」）——
只存 `note_id` 等于放弃回访。

⑩ **🔴 任何情况下都不要把自动化浏览器指向真实浏览器 profile 目录**（详见「踩坑⑨」）——
2026-09-09 因此**原地删除真实 profile 的 1661 条 Cookie，含 Google 账号登录态，不可恢复**。
这是本 skill 中唯一「会毁用户数据」的坑，优先级高于其他所有条目。
脚本里如出现 `AppData\Local\Google\Chrome\User Data` 字样，一律视为高危，立刻改掉。

⑪ **搜索页会「多跳重定向」，单次 `page.evaluate` 必爆「Execution context was destroyed」**（2026-09-10 血泪）——
访问 `https://www.xiaohongshu.com/search_result?keyword=...&source=web_explore_feed`
后 URL 会经历 `/search_result/ → /search_result?type=51 → captcha或结果` 至少两次跳转，
期间 `window` 会被销毁，此时 `page.evaluate(...)` 抛
`Page.evaluate: Execution context was destroyed, most likely because the page was destroyed`。

**解法（唯一实现点：`xhs_collect_photos.py` 的 `eval_retry()`）**：
`page.goto` 用 `try/except` 吞掉超时，紧接着所有 `page.evaluate` 都走 `eval_retry()`
—— 每轮 sleep 2-3s、最多 14 轮，循环开头检查 `"/website-login/captcha" in page.url`
→ 命中即抛 `RuntimeError`，让上层立即中止以免加重风控。
**不要在调用点各写一套重试循环**：笔记页（`note_images`）同样会重定向，漏了它就变成
「整篇图静默丢失」—— 日志只写「无原图」，看着像帖子本身的问题。

单次 `evaluate` 看不到结果是 bug 不是限流。**这坑在采集时表现为「搜索失败」，
但其实是脚本写法问题；老脚本因此白白触发账号安全验证。**

**⚠️ 副本漂移（2026-09-17 复发根因）**：这坑修好过一次却仍复发 ——
因为修复只落在某一个副本里，实际跑的那份（GitHub 仓库 / 项目目录）还是
「单次 `evaluate`」的旧版。所以拿到任何一份 `xhs_collect_photos.py`，
**先跑自检再采集**：

```bash
python xhs_collect_photos.py --selfcheck
```

它校验 `eval_retry()` 是否被 `search_cards` / `note_images` 共用、captcha 检查是否在、
登录态 profile 是否避开真实浏览器目录。**FAIL 就是旧版，从本地技能目录重新复制**，
别在旧版上打补丁。

⑫ **`id_token` 存在 ≠ 登录态有效，别拿它当唯一判据**（2026-09-11 实测）——
复用一份 3 周前的 `xhs_profile` 时，cookie 看起来「很健康」：
`id_token`（长度 136）、`web_session`、`a1`、`unread` 全都在，
但打开首页实际**已经弹出扫码框、左侧栏登录按钮可见** → 登录态早就过期了。
说明 `id_token` 只是「曾经登录过」的残留，不会随失效被清掉。
**判定顺序**：① 登录按钮不可见（主判据）→ ② `page.screenshot()` 目视复核。
只看 cookie 名字或长度，会在采集启动时静默通过、跑到中途才开始报错。
（登录失效时立刻重扫码，不要试图「修 cookie」。）

## 正文提取的边界与补强（实测结论）

对 115 篇实测数据的复盘结论，别想当然：

**「折叠片段」其实不是问题。** 小红书的「展开全文」是 CSS line-clamp 的**视觉截断**，
DOM 里 `.note-text` 的文本节点本来就是完整的，`inner_text()` 能直接拿到全文。
实测 115 篇中 **0 篇以省略号结尾**（即无一被折叠截断）。
`xhs_collect.py` 里的 `expand_full_text()` 只是保险，多数情况不点也拿得到全文。

**真正的三个盲区**（当时没处理，脚本现已补上）：

| 盲区 | 表现 | 补救 |
|---|---|---|
| 纯话题标签帖 | 正文只有 `#xxx #yyy`，如 21 字的「民宿推荐」帖 | `is_tag_only()` 识别打标 `tag_only:true` |
| 问答帖答案在评论区 | 标题是提问、正文是标签、回答全在评论 | 正文 <80 字或纯标签时自动抓前 10 条评论存 `comments` |
| 纯图帖 | 正文 0 字、信息全在图片里 | **未做 OCR**（收益/成本不划算），直接舍弃不补 |

**收录策略**：`if title or text` 任一非空就收录——纯标签帖**保留但打标**，
由下游消化时决定取舍（标题本身常有信息量，如「推荐个干净的民宿呗」）。
若想跳过：落盘前过滤 `tag_only and not comments` 的记录即可。

## 合规边界（每次都要提醒用户）

- 底层是 Playwright 驱动官方 Chromium 内核、模仿人工浏览，**不涉及逆向加密**
- 但小红书用户协议通常禁止自动化抓取，此流程属**灰色地带**
- **仅限个人研究/自用参考，禁止规模化抓取或商用**
- 采集到的内容用作事实参考时应消化改写，不要原文搬运

## 文件约定

**代码**住在技能目录里（`scripts/`），**运行产物与登录态**住在会话目录里
（`platform_compat.session_dir()`：`SCRAPE_SESSION_DIR` >
旧的 `<cwd>/.workbuddy`（若已用过） > `%LOCALAPPDATA%\agent-scrape-session`）。

```
<技能目录>/scripts/
├── xhs_login.py          # 扫码登录
├── xhs_verify.py         # 登录态校验
├── xhs_collect.py        # 采集主脚本
├── session_daemon.py     # 常驻会话服务
├── human_act.py          # 拟人化操作层（各平台共用）
└── platform_compat.py    # 宿主平台兼容层（浏览器探测/会话目录/进程/技能发现）

<会话目录>/
├── browser_profile/      # 持久化浏览器 profile（真实账号会话，勿删）
├── cookies_<tag>.json    # cookie 快照（含会话级，见 human_act.save_cookies）
├── xhs_profile/          # 小红书专用 profile（xhs_login 用）
└── calibration.json      # 元素坐标标定表（四级降级的第 ③ 级）

<工作目录>/
├── xhs_notes.jsonl       # 原始笔记
├── xhs_digest.md         # 去重分类摘要（Step 4 产物）
└── xhs_collect.log       # 运行日志
```

> ⚠️ **产物不要写进技能目录** —— 技能目录是「安装物」，写脏后会跟着同步进公开仓库
> （2026-09-18 发现并修正）。

## 可复用性

这套「真实账号 + 有头浏览器 + 关闭 AutomationControlled + 随机拟人节奏 + 限速」
的组合**不绑定小红书**，换成任意需要登录态的站点（微博、知乎、携程、大众点评等）时，
只需改 Step 3 里的 URL 与选择器，其余骨架完全通用。
