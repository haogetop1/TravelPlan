---
name: xhs-humanized-collect
description: 小红书拟人化采集。用 Playwright 持久化登录态 + 真实有头浏览器 + 随机拟人节奏 + 限速，绕过风控批量采集笔记正文（标题/作者/点赞/日期/正文）。适用于需要以小红书实测帖为事实来源做攻略、选品、舆情、调研的场景。触发词：小红书采集、小红书搜索、xhs 采集、小红书避坑帖、登小红书抓数据、小红书攻略素材。
agent_created: true
---

# 小红书拟人化采集

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
登录态永久保存在项目 `.workbuddy/` 下，后续所有采集复用，不用再扫。

**配套的两个坑（必看）：**

- **登录判据不能用 `web_session` 长度** —— 未登录时 `web_session` 也是 38 位匿名值，
  用 `len(web_session) > 30` 判断会**误判成已登录**。唯一可靠判据是 **`id_token` 存在**。
- **二维码必须持续刷新** —— 每 20s 重新截图覆盖同一个 `qrcode.png`，
  用 `present_files` 展示该文件，用户看到的就是最新一张，避免「码过期了」的往返。

## 🚨 踩坑⑨（最高危 / 已造成真实数据损毁）：绝对禁止把自动化浏览器指向真实 profile 目录

**禁令（无条件遵守）：**

```
❌ 禁止 launch_persistent_context(r"C:\Users\<u>\AppData\Local\Google\Chrome\User Data", ...)
❌ 禁止 launch_persistent_context(r"...\Edge\User Data", ...)  # 同理
✅ 只用 <workspace>/.workbuddy/<name>_profile 这类独立 data dir
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

Windows 下用 WorkBuddy 的托管 Python：`<你的 WorkBuddy 目录>\binaries\python\envs\default\Scripts\python.exe`
（注意不是 `...\envs\default\python.exe`，那个路径不存在。
 实际路径请按自己机器上的 WorkBuddy 安装位置替换，不要把绝对路径提交进公开仓库。）

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

**解法**：`page.goto` 用 `try/except` 吞掉超时，紧接着在「evaluate 重试循环」里跑
（每次 sleep 2-3s，最多 14 轮），并在循环开头检查 `"/website-login/captcha" in page.url`
→ 命中即抛 `RuntimeError("CAPTCHA 拦截")`，让上层立即中止以免加重风控。

单次 `evaluate` 看不到结果是 bug 不是限流。**这坑在采集时表现为「搜索失败」，
但其实是脚本写法问题；老脚本因此白白触发账号安全验证。**

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

```
<工作区>/.workbuddy/
├── xhs_profile/          # 持久化浏览器 profile（真实账号会话，勿删）
├── xhs_cookies.json      # 登录 cookie 备份
├── xhs_login.py          # 扫码登录
├── xhs_verify.py         # 登录态校验
├── xhs_collect.py        # 采集主脚本
├── xhs_notes.jsonl       # 原始笔记
├── xhs_digest.md         # 去重分类摘要（Step 4 产物）
└── xhs_collect.log       # 运行日志
```

## 可复用性

这套「真实账号 + 有头浏览器 + 关闭 AutomationControlled + 随机拟人节奏 + 限速」
的组合**不绑定小红书**，换成任意需要登录态的站点（微博、知乎、携程、大众点评等）时，
只需改 Step 3 里的 URL 与选择器，其余骨架完全通用。
