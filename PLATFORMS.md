# 平台支持矩阵（Platforms）

**支持范围：Windows 10/11（x64）。** 目标宿主：**任意 agent 平台**。
macOS / Linux **不在支持范围**（代码里留了极少量 POSIX 兜底分支，
只为万一在 WSL 里跑不至于直接崩，**未经测试**，不要依赖）。

---

## 一、宿主 agent 平台

| 宿主 | 技能目录 | 是否认 `SKILL.md` | 入口文件 | 装法 |
|---|---|---|---|---|
| **WorkBuddy / CodeBuddy** | `~/.workbuddy/skills/` | ✅ 是（原生 Agent Skills） | 不需要 | `install.py --target workbuddy` |
| **Claude Code** | `~/.claude/skills/` | ✅ 是（同属 Agent Skills） | 项目 `CLAUDE.md`、`~/.claude/CLAUDE.md`、`AGENTS.md` | `--target claude` |
| **Codex CLI (OpenAI)** | `%LOCALAPPDATA%\agent-skills\skills\` | ❌ 否 | 项目 `AGENTS.md`、`~/.codex/AGENTS.md` | `--target codex` |
| **Cursor** | 同上 | ❌ 否 | 项目 `AGENTS.md`、`.cursor/rules/travelplan.mdc` | `--target cursor` |
| **Gemini CLI** | 同上 | ❌ 否 | 项目 `GEMINI.md`、`~/.gemini/GEMINI.md`、`AGENTS.md` | `--target gemini` |
| **Windsurf** | 同上 | ❌ 否 | 项目 `AGENTS.md`、`.windsurf/rules/travelplan.md` | `--target windsurf` |
| **其它**（Zed / Amp / Jules…） | 同上 | ❌ 否 | 项目 `AGENTS.md` | `--target generic` |

一键装到本机检测到的全部宿主：`py -3 install.py --target auto`。

> 不认 `SKILL.md` 的平台拿到的是**浓缩操作说明**（由 `install.py` 生成，
> 含硬约束与常见坑），权威规则仍在各技能的 `SKILL.md` / `references/` 里。

---

## 二、能力在平台间的可用性

| 能力 | 依赖 | 跨平台情况 |
|---|---|---|
| 生成攻略 `.xlsx`（5 sheet / 冻结 / 富文本 / 环形图 / 内嵌地图） | `openpyxl` | ✅ 纯 Python，与平台无关 |
| 图文路书 **HTML**（Jinja2 渲染） | `jinja2` | ✅ 纯 Python |
| **PPT**（详细版 / 简洁版） | `python-pptx` + 渲染截图 | ✅ 纯 Python；截图环节需要 Chromium |
| 分段截图验收 | `playwright` + Chromium | ✅ 只用于渲染，任何内核都行 |
| **PDF** | — | ⛔ **一律不由 agent 生成**，用户从 HTML 自行打印 |
| 小红书 / 携程 / 神州采集 | `playwright` + **原生 Chrome** + 登录态 | ✅ 但**必须原生 Chrome**（自带内核被风控拦） |
| 地图：天地图截图 | Playwright + 网页截图 | ✅ |
| 地图：高德静态地图 | 用户自备 Web 服务 key（`AMAP_WEB_KEY`） | ✅ |
| 常驻会话（CDP）+ cookie 快照 | 原生 Chrome + `human_act.py` | ⚠️ 见下方「已知限制」 |

---

## 三、已知限制（写清楚，别踩）

1. **进程级常驻在受沙箱保护的环境里不成立。** `DETACHED_PROCESS`、
   `CREATE_BREAKAWAY_FROM_JOB`、`cmd` 的 `start`、计划任务 —— 四种实测**全部**
   会在命令结束时被回收。真正管用的是 ①固定 profile（带过期时间的 cookie 会落盘）
   ②cookie 快照（`human_act.save_cookies/restore_cookies`，含会话级）。
   需要用户**手点**登录时，让用户自己启动窗口
   （`platform_compat.launch_instructions()` 生成那条命令）。
2. **某些沙箱会拉黑 `schtasks.exe` / `wmic.exe`**（程序黑名单，明确不允许绕过）。
   `session_daemon.py --schtasks` 因此默认关闭；`platform_compat.pids_with_arg()`
   在 Windows 上直接返回空 —— 存活判据统一用「CDP 端口可连通 + 状态文件里的 pid」。
3. **`m.zuche.com` 与 `www.zuche.com` 是两套独立会话**，H5 必须单独登录一次。
4. **高德网页版已被风控封死**（登录 + 滑块）；用**高德 Web 服务静态地图 API**
   （需 key）或天地图网页截图替代。
5. **macOS / Linux 未支持**：`platform_compat` 里有路径推演与 POSIX 兜底分支，
   但没在真机上验证过。要支持需要单独一轮验证，不要假定它能直接跑。

---

## 四、自检

```bat
:: 宿主平台兼容层：Windows 不变量 + 各宿主目标解析（40 项）
py -3 xhs-humanized-collect\scripts\platform_compat.py --selfcheck

:: 本机实际解析结果（Chrome / 会话目录 / 技能根候选）
py -3 xhs-humanized-collect\scripts\platform_compat.py --where

:: 本机装了哪些 agent 平台
py -3 xhs-humanized-collect\scripts\platform_compat.py --agents

:: 采集器的踩坑⑪ 防护自检
py -3 travel-guide-builder\scripts\xhs_collect_photos.py --selfcheck

:: 拟人化操作层自检（四级降级 + 三件套 + 不关浏览器 + 平台中立）
py -3 xhs-humanized-collect\scripts\human_act.py --selfcheck

:: 支持哪些宿主 / 本机检测结果
py -3 install.py --list
```

---

## 五、许可证

仓库的 [`LICENSE`](LICENSE) 是 **MIT**（© 2026 haogetop1）。
两个技能的 `SKILL.md` frontmatter 也已补上 `license: MIT` —— 与仓库保持一致，
同时满足 Agent Skills 规范里的可选字段。
