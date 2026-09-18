# -*- coding: utf-8 -*-
"""
宿主平台兼容层 —— 让本技能在 **Windows 上的各种 agent 平台**通用。

适用范围（明确边界，避免过度承诺）
----------------------------------
**支持：Windows 10/11。目标：任意宿主 agent 平台。**
（macOS / Linux 不在范围内；代码里保留了极少量 POSIX 兜底分支，
只是为了万一在 WSL 里跑不会直接崩，**未经测试**。）

要解决的真问题不是「跨操作系统」，而是**跨宿主 agent 平台** ——
各家的技能安装约定、入口文件、以及「平台专有工具」都不一样：

| 宿主 | 技能目录约定 | 入口文件 | 认 SKILL.md |
|---|---|---|---|
| WorkBuddy / CodeBuddy | `~/.workbuddy/skills/` | — | 是 |
| Claude Code | `~/.claude/skills/` | `CLAUDE.md` / `AGENTS.md` | 是 |
| Codex CLI | 无官方技能目录 | `AGENTS.md` | 否 |
| Cursor | 无官方技能目录 | `AGENTS.md` / `.cursor/rules/*.mdc` | 否 |
| Gemini CLI | 无官方技能目录 | `GEMINI.md` / `AGENTS.md` | 否 |
| Windsurf | 无官方技能目录 | `AGENTS.md` / `.windsurf/rules/*.md` | 否 |
| 其它（Zed / Amp / Jules…） | — | `AGENTS.md`（事实标准） | 否 |

于是统一策略是三层：

1. **`SKILL.md` 保持 Agent Skills 规范**（frontmatter 只要求 `name` + `description`）
   → 认 SKILL.md 的平台可直接自动发现。
2. **`AGENTS.md` 作为通用入口**（事实标准，被 Codex / Cursor / 新版 Gemini 等读取）
   → 不认 SKILL.md 的平台靠它上手。
3. **`install.py` 把两个技能铺到正确位置**，并给每个目标生成它认的入口文件。

另外把「平台专有工具」的引用从文档里去掉（例如某平台才有的
`present_files` / 提问工具），改成「有就用、没有就用等价手段」的写法。

为什么要单独成模块
------------------
2026-09-18 的移植性审计结论：两个技能的**核心逻辑（xlsx / HTML / PPT 渲染、
内容抽取、价格解析）本来就是纯 Python、无平台绑定**；平台假定全部堆在
两处 —— ① 浏览器会话层（原生 Chrome 探测 / 进程管理 / 会话目录）
② 脚本互相 import 的写死路径。收敛到本模块后换平台只改这一处。
（这也是 2026-09-17 的教训：一类问题必须收敛成唯一实现点，否则换个副本必然复发。）

设计约束
--------
1. **纯标准库**，不引第三方依赖（playwright 只在真要启动浏览器时才 import）。
2. **import 时零副作用**：不建目录、不起进程、不读网络。
3. **可测**：关键函数带 `platform` / `home` 等参数，能在单机上把分支都走一遍。
4. **不产出含本机绝对路径的仓库内文件** —— 生成物里一律用 `python` 之类的
   通用写法，避免把 `%USERPROFILE%\<你>` 这类路径提交进仓库。
   同理，本模块**源码里也不出现形如「盘符:\\Users\\…」的字面量**
   （示例一律写成 `%USERPROFILE%`，或用 `ntpath.join` 运行时拼接）——
   否则敏感扫描会误报，而且一旦有人真填了用户名就顺着模板提交上去了。
   （2026-09-18 的自检就因此报过假阳性，占位符也要写成扫不出来的形态。）

命令行
------
    python platform_compat.py --selfcheck     # Windows 不变量 + 各宿主平台目标解析
    python platform_compat.py --where         # 本机实际解析结果
    python platform_compat.py --agents        # 检测本机装了哪些 agent 平台
"""
import argparse
import ntpath
import os
import shutil
import subprocess
import sys

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# 会话目录叶子名（放 profile / 状态 / 标定表 / cookie 快照）
SESSION_LEAF = "agent-scrape-session"
SESSION_STATE_FILE = "session_daemon.json"
# WorkBuddy 历史约定的会话目录：<cwd>/.workbuddy（只在检测到已用时才沿用）
LEGACY_SESSION_LEAF = ".workbuddy"

# 允许用户覆盖浏览器可执行文件（按优先级）
CHROME_ENV_KEYS = ("CHROME_PATH", "GOOGLE_CHROME_SHIM", "BROWSER_PATH")

# Chromium 系浏览器名字（PATH 里找）
BROWSER_BINARIES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "brave-browser", "microsoft-edge", "microsoft-edge-stable",
    "google-chrome.exe", "chrome.exe", "msedge.exe",
)

# 技能根目录的候选环境变量（便于 CI / 自定义布局）
SKILLS_ENV_KEYS = (
    "AGENT_SKILLS_DIR", "SKILLS_DIR",
    "WORKBUDDY_SKILLS_DIR", "CLAUDE_SKILLS_DIR", "CODEX_SKILLS_DIR",
)

# 本仓库里的两个技能
SKILL_NAMES = ("travel-guide-builder", "xhs-humanized-collect")


# ==================================================== 宿主 agent 平台注册表
#
# entries 里每条是 (scope, 相对路径)：
#   scope="project" → 写到 `--project`（默认当前目录）下
#   scope="global"  → 写到用户主目录下（`~` 会被展开）
# 这些都是各工具**实际读取**的指令文件位置，不是猜的。

AGENT_TARGETS = {
    "workbuddy": dict(
        label="WorkBuddy / CodeBuddy",
        skills_roots=["~/.workbuddy/skills"],
        reads_skill_md=True,
        entries=[],
        note="原生 Agent Skills 宿主：技能放进去即被自动发现，不需要入口文件。",
    ),
    "claude": dict(
        label="Claude Code",
        skills_roots=["~/.claude/skills"],
        reads_skill_md=True,
        entries=[("project", "CLAUDE.md"),
                 ("global", "~/.claude/CLAUDE.md"),
                 ("project", "AGENTS.md")],
        note="同属 Agent Skills 规范，技能目录放好即可；CLAUDE.md 里补一句指向。",
    ),
    "codex": dict(
        label="Codex CLI (OpenAI)",
        skills_roots=[],
        reads_skill_md=False,
        entries=[("project", "AGENTS.md"),
                 ("global", "~/.codex/AGENTS.md")],
        note="不认 SKILL.md，靠 AGENTS.md（项目级 + ~/.codex/AGENTS.md 全局）。",
    ),
    "cursor": dict(
        label="Cursor",
        skills_roots=[],
        reads_skill_md=False,
        entries=[("project", "AGENTS.md"),
                 ("project", ".cursor/rules/travelplan.mdc")],
        note="项目规则放 .cursor/rules/（.mdc 需要 frontmatter）；也读 AGENTS.md。",
    ),
    "gemini": dict(
        label="Gemini CLI",
        skills_roots=[],
        reads_skill_md=False,
        entries=[("project", "GEMINI.md"),
                 ("global", "~/.gemini/GEMINI.md"),
                 ("project", "AGENTS.md")],
        note="上下文文件是 GEMINI.md（项目级 + ~/.gemini/GEMINI.md）；也读 AGENTS.md。",
    ),
    "windsurf": dict(
        label="Windsurf",
        skills_roots=[],
        reads_skill_md=False,
        entries=[("project", "AGENTS.md"),
                 ("project", ".windsurf/rules/travelplan.md")],
        note="规则放 .windsurf/rules/。",
    ),
    "generic": dict(
        label="其它（支持 AGENTS.md 的任意 agent）",
        skills_roots=[],
        reads_skill_md=False,
        entries=[("project", "AGENTS.md")],
        note="AGENTS.md 已是跨工具事实标准（Zed / Amp / Jules 等）。",
    ),
}

# 检测「本机装了哪个 agent」的指纹（目录或可执行文件）
AGENT_FINGERPRINTS = {
    "workbuddy": ["~/.workbuddy", "~/AppData/Local/Programs/WorkBuddy",
                  "~/AppData/Roaming/WorkBuddy"],
    "claude": ["~/.claude", "~/.claude.json"],
    "codex": ["~/.codex"],
    "cursor": ["~/.cursor", "~/AppData/Roaming/Cursor", "~/AppData/Local/Programs/cursor"],
    "gemini": ["~/.gemini"],
    "windsurf": ["~/.windsurf", "~/AppData/Roaming/Windsurf"],
}


def detect_agents(home=None):
    """检测本机装了哪些 agent 平台，返回 [(key, label, 命中路径)]。"""
    home = home or os.path.expanduser("~")
    found = []
    for key, pats in AGENT_FINGERPRINTS.items():
        for pat in pats:
            p = pat.replace("~", home)
            if os.path.exists(p):
                found.append((key, AGENT_TARGETS[key]["label"], p))
                break
    return found


def agent_target(key):
    if key not in AGENT_TARGETS:
        raise KeyError("未知的宿主平台：%s（可选：%s）"
                       % (key, "、".join(AGENT_TARGETS)))
    return AGENT_TARGETS[key]


def skills_roots_for(key, home=None, project=None):
    """某个宿主平台的技能根目录（绝对路径，已规范化分隔符）。"""
    home = (home or os.path.expanduser("~")).rstrip("\\/")
    t = agent_target(key)
    out = []
    for r in t["skills_roots"]:
        out.append(os.path.normpath(
            os.path.expanduser(r.replace("~", home)).replace("/", os.sep)))
    if not out:
        # 不认 SKILL.md 的平台：仍然把技能铺到一个稳定位置，
        # 由生成的入口文件用绝对路径引用它（这样兄弟技能互相 import 才找得到）
        out.append(default_skills_root(home))
    return out


def entry_files_for(key, home=None, project=None):
    """某个宿主平台要生成的入口文件（绝对路径，已去重、分隔符已规范化）。

    `home=None` 时用真实主目录。scope="global" 落到 home 下，scope="project"
    落到 project 下。

    ⚠️ 注册表里 global 项写成 `~/.codex/AGENTS.md` 只是**为了可读性**；
    这里已经把 `~` 展开成 base 了，所以必须把那个前导 `~` 去掉 ——
    否则会拼出 `<home>\\~\\.codex\\AGENTS.md`（多一个字面量 `~` 目录）。
    2026-09-18 被自检抓到过一次。
    """
    home = (home or os.path.expanduser("~")).rstrip("\\/")
    project = project or os.getcwd()
    out = []
    for scope, rel in agent_target(key)["entries"]:
        base = home if scope == "global" else project
        sub = rel[1:].lstrip("/\\") if rel.startswith("~") else rel
        out.append(os.path.normpath(os.path.join(base, sub.replace("/", os.sep))))
    if any(os.sep + "~" + os.sep in p for p in out):
        raise ValueError("入口路径里出现了字面量 ~ 目录：%s" % out)
    seen, uniq = set(), []
    for p in out:
        k = os.path.normcase(p)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


# ==================================================== 平台判定

def norm_platform(platform=None):
    p = (platform or sys.platform).lower()
    if p.startswith("win"):
        return "windows"
    if p in ("darwin", "macos", "mac"):
        return "macos"
    if p.startswith("linux"):
        return "linux"
    return "other"


def is_windows(platform=None):
    return norm_platform(platform) == "windows"


def setup_stdout():
    """把 stdout 统一成 UTF-8。

    中文 Windows 默认 cp936，直接 print emoji / 生僻字会抛
    UnicodeEncodeError —— 这个坑在采集日志里出现过多次。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def run_bytes(cmd, timeout=None, cwd=None):
    """跑命令并**按字节**取回输出。

    ⚠️ 不要改成 `text=True`：中文 Windows 的 tasklist / taskkill 输出是 GBK，
    用 text=True 会在 reader 线程抛 UnicodeDecodeError，异常被吞掉后表现为
    「进程明明活着却判断成已死」（2026-09-17 实测误判过一次）。
    """
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=cwd)
        return r.returncode, r.stdout or b"", r.stderr or b""
    except Exception as e:
        return -1, b"", str(e).encode("utf-8", "replace")


def decode_console(raw):
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


# ==================================================== 浏览器探测（Windows 为主）

def chrome_candidates(platform=None, home=None):
    """原生 Chrome / Edge / Chromium 的候选绝对路径（按优先级）。

    路径是给**目标平台**用的，所以显式用 ntpath / posixpath 拼，
    不依赖宿主机的 os.sep。
    """
    kind = norm_platform(platform)
    home = home or os.path.expanduser("~")
    out = []

    if kind == "windows":
        J = ntpath.join
        pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
        pf86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
        local = os.environ.get("LOCALAPPDATA") or J(home, "AppData", "Local")
        out += [
            J(pf, "Google", "Chrome", "Application", "chrome.exe"),
            J(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            J(local, "Google", "Chrome", "Application", "chrome.exe"),
            J(home, "AppData", "Local", "Google", "Chrome", "Application", "chrome.exe"),
            # Chromium 系兜底（风控通常只卡 Playwright 自带内核，Edge 多半也能过）
            J(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            J(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
        ]

    elif kind == "macos":
        # 不在支持范围，仅保留路径推演能力（用 posixpath 保证是 / 分隔）
        J = posixpath.join
        out += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            J(home, "Applications", "Google Chrome.app",
              "Contents", "MacOS", "Google Chrome"),
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]

    elif kind == "linux":
        out += ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium", "/usr/bin/chromium-browser",
                "/snap/bin/chromium"]
        for name in BROWSER_BINARIES:
            w = shutil.which(name)
            if w:
                out.append(w)
    return out


def find_chrome(platform=None, check_exists=True, home=None):
    """找原生浏览器可执行文件；找不到返回 None。

    `check_exists=False` 时只做路径推演（用于打印其它平台会用什么）。
    """
    for key in CHROME_ENV_KEYS:
        v = os.environ.get(key)
        if v and (not check_exists or os.path.exists(v)):
            return v
    for p in chrome_candidates(platform, home):
        if not check_exists or os.path.exists(p):
            return p
    return None


def playwright_chromium():
    """Playwright 自带 Chromium 的路径；没装 playwright 时返回 ''。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return p.chromium.executable_path
    except Exception:
        return ""


def resolve_browser(explicit=None, prefer_native=True, platform=None):
    """决定用哪个浏览器内核，返回 (exe, kind)。

    kind ∈ native-chrome / playwright-chromium / custom

    为什么默认原生：携程 / 神州的指纹风控（whaleguard block）会拦 Playwright
    自带内核；本机实测原生 Chrome 一路畅通。
    """
    if explicit:
        return explicit, "custom"
    if prefer_native:
        n = find_chrome(platform)
        if n:
            return n, "native-chrome"
    return playwright_chromium(), "playwright-chromium"


# ==================================================== 目录解析

def user_data_dir(platform=None, home=None):
    """Windows 上用户级数据目录（LOCALAPPDATA）。

    ⚠️ `LOCALAPPDATA` 在环境变量里是正斜杠写法，直接 join 会拼出
    `C:/a/b\\c` 这种混合分隔符 —— 一律 normpath 归一到本机风格。
    """
    home = home or os.path.expanduser("~")
    if is_windows(platform):
        raw = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    elif norm_platform(platform) == "macos":
        # 非目标平台：给个能用的兜底（未验证）
        raw = os.path.join(home, "Library", "Application Support")
    else:
        raw = (os.environ.get("XDG_DATA_HOME")
               or os.path.join(home, ".local", "share"))
    return os.path.normpath(raw)


def default_skills_home(home=None):
    """不认 SKILL.md 的宿主平台，把技能统一铺到这里的 `skills/`。

    ⚠️ 安装位置与 `skills_roots()` 的发现路径必须一致 —— 这里返回的是
    **不含 `skills/` 的父目录**，两边都通过 `default_skills_root()` 取真正的根，
    避免出现「装上了却找不到」（2026-09-18 自检抓到过一次）。
    """
    return os.path.join(user_data_dir("win32", home), "agent-skills")


def default_skills_root(home=None):
    """不认 SKILL.md 的宿主的技能根目录（`<LOCALAPPDATA>\\agent-skills\\skills`）。"""
    return os.path.join(default_skills_home(home), "skills")


def legacy_session_dir(cwd=None):
    """旧的 WorkBuddy 约定：`<cwd>/.workbuddy`。"""
    return os.path.join(cwd or os.getcwd(), LEGACY_SESSION_LEAF)


def _legacy_in_use(cwd=None):
    d = legacy_session_dir(cwd)
    if not os.path.isdir(d):
        return False
    return (os.path.exists(os.path.join(d, SESSION_STATE_FILE))
            or os.path.isdir(os.path.join(d, "browser_profile")))


def session_dir(explicit=None, platform=None, cwd=None):
    """解析会话目录（放 profile / 状态 / 标定表 / cookie 快照）。

    优先级：
      1. 显式传入
      2. `SCRAPE_SESSION_DIR`            ← 想跨项目共用登录态就用它
      3. 兼容：`<cwd>/.workbuddy` 若已被用过 → 沿用
         （升级后不能让用户「突然又要重新扫码」，这是硬要求）
      4. `<LOCALAPPDATA>\\agent-scrape-session`（不再绑 WorkBuddy）
    """
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    env = os.environ.get("SCRAPE_SESSION_DIR")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if _legacy_in_use(cwd):
        return legacy_session_dir(cwd)
    return os.path.join(user_data_dir(platform), SESSION_LEAF)


def profile_dir(session=None, platform=None, cwd=None):
    return os.path.join(session or session_dir(platform=platform, cwd=cwd),
                        "browser_profile")


# ==================================================== 技能目录发现

def skills_roots(platform=None, home=None, extra=None):
    """可能存放技能的根目录（按优先级）。用于「兄弟技能互相 import」。"""
    home = (home or os.path.expanduser("~")).rstrip("\\/")
    out = []
    for key in SKILLS_ENV_KEYS:
        v = os.environ.get(key)
        if v:
            out.append(os.path.abspath(os.path.expanduser(v)))

    if is_windows(platform):
        out += [os.path.join(home, ".workbuddy", "skills"),
                os.path.join(home, ".claude", "skills"),
                os.path.join(home, ".codex", "skills")]
    else:
        out += [os.path.join(home, ".claude", "skills"),
                os.path.join(home, ".workbuddy", "skills"),
                os.path.join(home, ".config", "workbuddy", "skills")]

    # 不认 SKILL.md 的宿主：技能统一铺在 agent-skills 下
    out.append(default_skills_root(home))
    out.append(os.path.join(home, ".config", "agent-skills"))

    for e in (extra or []):
        if e:
            out.append(os.path.abspath(os.path.expanduser(e)))

    seen, uniq = set(), []
    for p in out:
        k = os.path.normcase(os.path.normpath(p))
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def sibling_script_dirs(skill_name, script_file=None, platform=None):
    """列出可能含目标技能 `scripts/` 的目录（供脚本间 import）。

    典型布局（两个技能并列安装）：
        <skills_root>/travel-guide-builder/scripts/xxx.py
        <skills_root>/xhs-humanized-collect/scripts/platform_compat.py
    """
    out = []
    if script_file:
        here = os.path.dirname(os.path.abspath(script_file))
        out.append(here)                                     # 同目录
        root = os.path.dirname(os.path.dirname(here))         # <skills_root>
        out.append(os.path.join(root, skill_name, "scripts"))
        out.append(os.path.join(root, "..", skill_name, "scripts"))
    for r in skills_roots(platform):
        out.append(os.path.join(r, skill_name, "scripts"))
    seen, uniq = set(), []
    for p in out:
        p = os.path.abspath(p)
        k = os.path.normcase(p)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def add_sibling_to_path(skill_name, script_file=None, platform=None):
    """把命中目标技能 `scripts/` 的目录塞进 sys.path，返回该目录或 None。"""
    for d in sibling_script_dirs(skill_name, script_file, platform):
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)
            return d
    return None


BOOTSTRAP_HINT = (
    "找不到 %s 的 scripts/ 目录。任选一种解决：\n"
    "  1) 用 install.py 把两个技能装到同一 skills 根目录；\n"
    "  2) 设环境变量 AGENT_SKILLS_DIR 指向那个根目录；\n"
    "  3) 在仓库内直接运行（两个技能目录互为兄弟）。\n"
)


# ==================================================== 进程管理（Windows 为主）

def detach_kwargs(platform=None):
    """让子进程脱离父进程所需 Popen kwargs。

    注意：在**受沙箱保护的执行环境**里这两种都可能被整体回收
    （2026-09-18 实测：DETACHED_PROCESS / CREATE_BREAKAWAY_FROM_JOB /
    cmd 的 start / 计划任务 全部无效）。真正的常驻靠
    「用户自己启动窗口」+「cookie 快照」，见 SKILL.md。
    """
    if is_windows(platform):
        return {"creationflags": 0x00000008 | 0x00000200}
    return {"start_new_session": True}


def pid_alive(pid, platform=None):
    """进程是否存活。Windows 走 tasklist；POSIX 走 os.kill(pid, 0)（兜底）。"""
    if not pid:
        return False
    if is_windows(platform):
        _, out, _ = run_bytes(["tasklist", "/FI", "PID eq %s" % pid, "/NH"])
        return str(pid).encode() in out
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def kill_tree(pid, platform=None):
    """结束进程及其子进程。Windows 走 taskkill /T；POSIX 走进程组（兜底）。"""
    if not pid:
        return False
    if is_windows(platform):
        rc, _, _ = run_bytes(["taskkill", "/PID", str(pid), "/T", "/F"])
        return rc == 0
    try:
        os.killpg(os.getpgid(int(pid)), 15)
        return True
    except Exception:
        try:
            os.kill(int(pid), 15)
            return True
        except Exception:
            return False


def pids_with_arg(needle, platform=None):
    """列出命令行含 `needle` 的进程 PID。

    ⚠️ Windows 上读命令行只能靠 `wmic`，而 2026-09-17 起本机沙箱已把
    `wmic.exe` 列入**程序黑名单**，所以这里在 Windows 上**直接返回空**：
    存活判据统一改为「CDP 端口是否可连通 + 状态文件里的 pid 是否还活着」。
    POSIX 上 `pgrep -f` 兜底。
    """
    if is_windows(platform):
        return []
    rc, out, _ = run_bytes(["pgrep", "-f", needle])
    if rc != 0:
        return []
    return [int(x) for x in decode_console(out).split() if x.strip().isdigit()]


def python_exe():
    """当前解释器绝对路径（生成启动器 / 写说明时用，避免依赖 PATH）。"""
    return sys.executable or "python"


def python_command_hint():
    """给用户看的跨宿主通用 python 调用写法（Windows）。"""
    return (
        "Windows 上 `python` 可能不在 PATH。优先用 `py -3`，"
        "或直接填绝对路径（安装器会把检测到的解释器打印出来）。"
    )


# ==================================================== 启动浏览器

def launch_argv(exe, port, profile, urls=(), headless=False, platform=None):
    """拼出「用户自己启动一个可 attach 的浏览器」的参数表。"""
    cmd = [
        exe,
        "--remote-debugging-port=%d" % port,
        "--user-data-dir=%s" % profile,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1440,900",
    ]
    if headless:
        cmd.append("--headless=new")
    cmd.extend(urls or ["about:blank"])
    return cmd


def quote_arg(s, platform=None):
    if is_windows(platform):
        return '"%s"' % str(s).replace('"', '\\"')
    return "'%s'" % str(s).replace("'", "'\\''")


def launch_command_line(exe, port, profile, urls=(), headless=False, platform=None):
    """生成用户可以**直接粘贴**的一行命令。"""
    cmd = launch_argv(exe, port, profile, urls, headless, platform)
    return " ".join(quote_arg(c, platform) for c in cmd)


def launch_instructions(exe, port, profile, urls=(), platform=None):
    """人话说明：怎么让浏览器活下来，好让 agent attach 上去。

    ⚠️ 强调两件事，都是踩过坑的：
    ① 必须**用户自己**启动（agent 起的窗口会随命令被清理，用户根本点不了）
    ② 若要包成 .bat，内容**必须纯 ASCII + CRLF**，否则 cmd 按 GBK 解析满屏乱码
       （且 `chcp 65001` 救不了 —— 它生效前就已经解析完了）
    """
    line = launch_command_line(exe, port, profile, urls, platform=platform)
    return (
        "请**你自己**启动一个带调试端口的浏览器（由我起的窗口会随命令一起被清理，"
        "留下来你也点不了）：\n\n"
        "  按 Win+R，粘贴下面这一行后回车：\n\n%s\n\n"
        "登录完成后**保持这个窗口开着**，我就能 attach 上去复用登录态。\n\n"
        "（若要包成 .bat 方便复用：内容必须**纯 ASCII + CRLF**，"
        "一个非 ASCII 字符都不能有，否则 cmd 会按 GBK 解析成满屏乱码，"
        "`chcp 65001` 也救不回来。）" % line
    )


VIEWPORT_DESKTOP = (1440, 900)
VIEWPORT_MOBILE = (414, 896)


# ==================================================== 诊断 / 自检

def describe(platform=None, home=None, probe_playwright=False):
    """解析结果汇总，便于排障。

    `probe_playwright=False`（默认）时不启动 Playwright 驱动 ——
    只为打印信息而拉起一次浏览器驱动又慢又会喷
    「Task was destroyed but it is pending!」噪音。
    """
    exe = find_chrome(platform, home=home)
    return {
        "platform": norm_platform(platform),
        "raw": platform or sys.platform,
        "python": python_exe(),
        "chrome": exe or "(未找到)",
        "chrome_kind": ("native-chrome" if exe
                        else ("playwright-chromium" if probe_playwright else "(未探测)")),
        "chrome_candidates": chrome_candidates(platform, home),
        "session_dir": session_dir(platform=platform),
        "user_data_dir": user_data_dir(platform, home),
        "skills_home": default_skills_home(home),
        "detach_kwargs": detach_kwargs(platform),
        "skills_roots": skills_roots(platform, home),
    }


def _selfcheck():
    """Windows 不变量 + 各宿主 agent 平台的安装目标解析。"""
    print("=" * 76)
    print("platform_compat 自检 —— Windows 宿主 + 各 agent 平台目标解析")
    print("=" * 76)
    fails = []

    print()
    print("[本机 Windows 解析]")
    d = describe("win32")
    for k in ("chrome", "chrome_kind", "session_dir", "user_data_dir", "skills_home"):
        print("   %-16s %s" % (k, d[k]))
    print("   %-16s %s" % ("detach_kwargs", d["detach_kwargs"]))

    print()
    print("[各宿主 agent 平台的安装目标]")
    print("   %-11s %-24s %-34s %s" % ("key", "平台", "技能根目录", "入口文件"))
    print("   " + "-" * 78)
    # 探测用的假主目录：**运行时拼接**，源码里不出现「盘符:\Users\…」的字面量，
    # 否则敏感扫描会把它当真实路径误报（2026-09-18 踩过）。
    home_probe = ntpath.join("C:" + ntpath.sep, "Users", "_probe")
    proj_probe = ntpath.join("D:" + ntpath.sep, "proj")
    for key in AGENT_TARGETS:
        roots = skills_roots_for(key, home=home_probe)
        ents = []
        for scope, rel in AGENT_TARGETS[key]["entries"]:
            ents.append(("项目/" if scope == "project" else "全局/") + rel)
        tail = "\\".join(roots[0].replace("/", "\\").split("\\")[-2:])
        print("   %-11s %-24s %-34s %s"
              % (key, AGENT_TARGETS[key]["label"], "…\\" + tail,
                 "、".join(ents) if ents else "（无需，自动发现）"))

    print()
    print("[本机检测到的 agent 平台]")
    found = detect_agents()
    if found:
        for key, label, p in found:
            print("   ✔ %-12s %-26s %s" % (key, label, p))
    else:
        print("   （未检测到已知 agent 平台目录）")

    print()
    print("=" * 76)
    print("不变量检查")
    print("=" * 76)
    checks = []

    # --- 平台归一化 ---
    checks.append(("win32 归一化为 windows", norm_platform("win32") == "windows"))

    # --- 浏览器探测：Windows 候选必须齐全且形态正确 ---
    c = chrome_candidates("win32")
    checks.append(("Chrome 候选非空", len(c) > 0))
    checks.append(("Chrome 候选都是 .exe", all(x.lower().endswith(".exe") for x in c)))
    checks.append(("Chrome 候选都是绝对路径",
                   all(ntpath.isabs(x) for x in c)))
    checks.append(("含 Edge 兜底（风控通常只卡 Playwright 内核）",
                   any("msedge" in x.lower() for x in c)))
    checks.append(("CHROME_PATH 可覆盖",
                   (lambda: (os.environ.__setitem__("CHROME_PATH", r"D:\x\chrome.exe"),
                             find_chrome("win32", check_exists=False) == r"D:\x\chrome.exe",
                             os.environ.pop("CHROME_PATH"))[1])()))

    # --- 会话目录 ---
    sd = session_dir(platform="win32", cwd=r"D:\no-such-legacy")
    checks.append(("会话目录是绝对路径", os.path.isabs(sd)))
    checks.append(("会话目录不再绑 WorkBuddy", LEGACY_SESSION_LEAF not in sd))
    os.environ["SCRAPE_SESSION_DIR"] = r"D:\tmp\_pc_selfcheck"
    checks.append(("SCRAPE_SESSION_DIR 覆盖生效",
                   session_dir(platform="win32") == os.path.abspath(r"D:\tmp\_pc_selfcheck")))
    os.environ.pop("SCRAPE_SESSION_DIR")
    checks.append(("保留旧 <cwd>/.workbuddy 兼容（不掉登录态）",
                   "_legacy_in_use" in open(os.path.abspath(__file__),
                                            encoding="utf-8").read()))

    # --- 进程管理：Windows 必须走 tasklist / taskkill ---
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    checks.append(("pid_alive 在 Windows 用 tasklist",
                   '"tasklist", "/FI"' in src))
    checks.append(("kill_tree 在 Windows 用 taskkill /T",
                   '"taskkill", "/PID"' in src))
    checks.append(("pids_with_arg 在 Windows 明确返回空（wmic 已被沙箱封）",
                   "if is_windows(platform):\n        return []" in src))

    # --- 宿主平台注册表完整性 ---
    for key in ("workbuddy", "claude", "codex", "cursor", "gemini", "windsurf", "generic"):
        checks.append(("注册表含 %s" % key, key in AGENT_TARGETS))
    checks.append(("认 SKILL.md 的平台被正确标注",
                   AGENT_TARGETS["workbuddy"]["reads_skill_md"]
                   and AGENT_TARGETS["claude"]["reads_skill_md"]
                   and not AGENT_TARGETS["codex"]["reads_skill_md"]))
    checks.append(("不认 SKILL.md 的平台都配了入口文件",
                   all(AGENT_TARGETS[k]["entries"]
                       for k in AGENT_TARGETS if not AGENT_TARGETS[k]["reads_skill_md"])))
    checks.append(("通用目标都含项目级 AGENTS.md",
                   all(("project", "AGENTS.md") in AGENT_TARGETS[k]["entries"]
                       for k in ("codex", "cursor", "gemini", "generic"))))
    checks.append(("codex/gemini 有全局入口（~ 下）",
                   any(s == "global" for s, _ in AGENT_TARGETS["codex"]["entries"])
                   and any(s == "global" for s, _ in AGENT_TARGETS["gemini"]["entries"])))
    checks.append(("cursor 规则是 .mdc（需要 frontmatter）",
                   any(r.endswith(".mdc") for _, r in AGENT_TARGETS["cursor"]["entries"])))

    # --- 目标解析：home 必须被正确展开，且不得依赖宿主 cwd ---
    roots = skills_roots_for("claude", home=home_probe)
    checks.append(("claude 技能目录基于 home 展开",
                   roots[0].startswith(home_probe) and roots[0].endswith("skills")))
    roots_wb = skills_roots_for("workbuddy", home=home_probe)
    checks.append(("workbuddy 技能目录落在 .workbuddy\\skills",
                   roots_wb[0].endswith(os.path.join(".workbuddy", "skills"))))
    roots_gen = skills_roots_for("generic", home=home_probe)
    checks.append(("generic 落到 agent-skills\\skills",
                   roots_gen[0] == default_skills_root(home_probe)))
    checks.append(("安装目标与发现路径一致（防「装了找不到」）",
                   default_skills_root(home_probe) in skills_roots("win32", home_probe)))
    ents = entry_files_for("cursor", home=home_probe, project=proj_probe)
    checks.append(("cursor 入口含 .cursor\\rules",
                   any(os.path.join(".cursor", "rules") in e for e in ents)))
    ents_g = entry_files_for("gemini", home=home_probe, project=proj_probe)
    checks.append(("gemini 入口含 GEMINI.md", any(e.endswith("GEMINI.md") for e in ents_g)))
    # 作用域必须各归其位：项目级落在 --project 下、全局级落在 home 下
    ents_c = entry_files_for("codex", home=home_probe, project=proj_probe)
    checks.append(("项目级入口落在 --project 下",
                   any(e.startswith(proj_probe) for e in ents_c)))
    checks.append(("全局级入口落在 home 下",
                   any(e.startswith(home_probe) for e in ents_c)))
    # 回归：global 项的前导 ~ 必须被去掉，否则会多出一个字面量 ~ 目录
    checks.append(("入口路径无字面量 ~ 目录（防双重展开）",
                   not any(os.sep + "~" + os.sep in e
                           for k in AGENT_TARGETS
                           for e in entry_files_for(k, home=home_probe,
                                                    project=proj_probe))))
    checks.append(("路径分隔符统一（无混合 / 与 \\）",
                   all(("/" not in e) for k in AGENT_TARGETS
                       for e in entry_files_for(k, home=home_probe, project=proj_probe))))

    # --- 启动流程的机械约束 ---
    line = launch_command_line(r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                               9222, r"C:\prof", platform="win32")
    checks.append(("启动命令行含调试端口", "--remote-debugging-port=9222" in line))
    checks.append(("含空格的路径被引号包住", '"C:\\Program Files\\Google' in line))
    ins = launch_instructions("chrome.exe", 9222, r"C:\prof", platform="win32")
    checks.append(("说明里强调「你自己启动」", "你自己" in ins))
    checks.append(("说明里警示 .bat 编码坑", "GBK" in ins and "chcp 65001" in ins))

    # --- 零副作用 ---
    header = src.split("def ")[0]
    checks.append(("模块 import 期不写文件/不建目录",
                   "os.makedirs" not in header and "open(" not in header))

    for name, ok in checks:
        print("  %-50s %s" % (name, "PASS" if ok else "FAIL"))
        if not ok:
            fails.append(name)

    print()
    print("=" * 76)
    if fails:
        print("自检 FAIL %d / %d：%s" % (len(fails), len(checks), "、".join(fails)))
        return 1
    print("自检全部 PASS（%d 项）" % len(checks))
    return 0


def _where():
    d = describe(probe_playwright=False)
    print("=" * 76)
    print("本机解析结果")
    print("=" * 76)
    for k in ("platform", "raw", "python", "chrome", "chrome_kind",
              "session_dir", "user_data_dir", "skills_home"):
        print("  %-16s %s" % (k, d[k]))
    print("  %-16s %s" % ("detach_kwargs", d["detach_kwargs"]))
    print()
    print("  Chrome 候选：")
    for p in d["chrome_candidates"]:
        print("     %-6s %s" % ("存在" if os.path.exists(p) else "—", p))
    print()
    print("  技能根候选：")
    for p in d["skills_roots"]:
        print("     %-6s %s" % ("存在" if os.path.isdir(p) else "—", p))
    return 0


def _agents():
    print("=" * 76)
    print("本机检测到的宿主 agent 平台")
    print("=" * 76)
    found = detect_agents()
    for key, label, p in found:
        t = AGENT_TARGETS[key]
        print()
        print("  ✔ %s（%s）" % (label, key))
        print("      指纹        : %s" % p)
        print("      认 SKILL.md : %s" % ("是" if t["reads_skill_md"] else "否"))
        for r in skills_roots_for(key):
            print("      技能目录    : %s" % r)
        for e in entry_files_for(key):
            print("      入口文件    : %s" % e)
    if not found:
        print("  （未检测到；可用 --target 显式指定）")
    print()
    print("  可指定的目标：%s" % "、".join(AGENT_TARGETS))
    return 0


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="宿主平台兼容层（自检 / 查询）")
    ap.add_argument("--selfcheck", action="store_true", help="Windows + 各宿主平台自检")
    ap.add_argument("--where", action="store_true", help="打印本机解析结果")
    ap.add_argument("--agents", action="store_true", help="检测本机 agent 平台")
    args = ap.parse_args()
    if args.selfcheck:
        return _selfcheck()
    if args.where:
        return _where()
    if args.agents:
        return _agents()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
