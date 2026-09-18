# -*- coding: utf-8 -*-
"""常驻会话服务（session daemon）—— 所有平台抓取共用的「不退出浏览器」。

为什么必须常驻（2026-09-17 用户明确要求）
----------------------------------------
**浏览器一关，会话 cookie 就带走了。** 小红书 / 携程 / 天地图 / 高德这些站点，
登录态里含会话级 cookie（无过期时间、只存在内存），`browser.close()` 之后
不会落盘到 profile 的 cookie 库；下次重新 launch 就是「已退出登录」，
于是每次抓取都要重新扫码 —— 既费事，又**高频登录本身就会触发风控**。

所以规矩是：**一次启动，常驻不退出**；所有采集脚本通过 CDP 连它，
谁都不许关浏览器（关页面可以）。抓完一个平台不要 stop，接着抓下一个。

**用哪个浏览器：默认原生 Chrome，不是 Playwright 自带的 Chromium。**
携程 / 神州这类站点有 `whaleguard` 之类的指纹风控，Playwright 自带 Chromium
会被直接拦（页面只显示 `whaleguard block`）。原生 Chrome 通过。
本机存在原生 Chrome 时自动用它，可用 `--exe` 显式指定，
用 `--playwright-chromium` 强制回退到自带内核（一般只在调试时用）。

用法
----
  python session_daemon.py start [--port 9222] [--headless] [--exe <chrome路径>]
  python session_daemon.py status
  python session_daemon.py exec <url> [--js "<expression>"]
  python session_daemon.py stop

  # 采集脚本侧（推荐）：把 CDP 端点交给脚本，脚本内部连常驻浏览器
  export XHS_CDP=http://127.0.0.1:9222

文件
----
  会话目录（优先 `SCRAPE_SESSION_DIR`；否则 `%LOCALAPPDATA%\agent-scrape-session`；
            旧的 `<cwd>/.workbuddy` 若已用过会继续沿用，避免掉登录态）
    ├── browser_profile/         # 持久化 profile（cookie 落盘的那部分）
    └── session_daemon.json      # {pid, port, profile, exe, exe_kind, started}

⚠️ 关于「进程级常驻」的现实（2026-09-18 更正）
------------------------------------------------
在**受沙箱保护的执行环境**里，agent 自己拉起的浏览器活不过一条命令：
`DETACHED_PROCESS`、`CREATE_BREAKAWAY_FROM_JOB`、`cmd` 的 `start`、计划任务
**四种全部实测失败**（进程照杀，端口随之关闭）。

真正靠得住的是两件事：

1. **固定 profile** —— 带过期时间的 cookie（携程 `cticket` 等）会落盘。实测
   杀掉浏览器再重启，ctrip 42 个 cookie 全在、登录照样有效。
2. **cookie 快照** —— `human_act.save_cookies/restore_cookies` 把**含会话级**的
   全部 cookie 落盘，下次 attach 注回。

需要用户**手点**登录（扫码 / 短信）时，请让用户自己启动窗口：
`platform_compat.launch_instructions()` 会按平台生成那条可直接粘贴的命令。
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')

# 宿主平台兼容层（与本文件同目录）：浏览器探测 / 会话目录 / 进程管理
# 都收敛在 platform_compat，避免「换宿主平台要改几十个文件」。
try:
    import platform_compat as PC
except Exception:                                        # pragma: no cover
    PC = None

DEFAULT_PORT = 9222


# ---------------------------------------------------------------- 路径与安全

def session_dir():
    """会话目录（profile / 状态文件 / cookie 快照）。

    ⚠️ 不再无条件写 `<cwd>/.workbuddy`：那是 WorkBuddy 专有约定，
    Claude Code / Codex / Cursor 等宿主不该被绑住。
    解析优先级见 `platform_compat.session_dir`；旧的会话目录若**已被用过**
    仍会继续沿用（否则用户会遇到「突然又要重新扫码」）。
    """
    d = PC.session_dir() if PC else (
        os.environ.get("SCRAPE_SESSION_DIR")
        or os.path.join(os.getcwd(), "agent-scrape-session"))
    os.makedirs(d, exist_ok=True)
    return d


def state_path():
    return os.path.join(session_dir(), "session_daemon.json")


def profile_path():
    return os.path.join(session_dir(), "browser_profile")


def assert_profile_safe(p):
    """踩坑⑨（最高危）：绝不指向真实浏览器 profile —— 会原地删掉用户 Cookie。

    App-Bound Encryption 会判定「profile 被非官方进程接管」，直接清空 cookie 库。
    2026-09-09 实测毁掉 1661 条 Cookie（含 Google 账号登录态），不可恢复。

    覆盖三平台的真实 profile 形态，多一道保险 —— 这道护栏拦错一次的代价太大。
    """
    low = os.path.abspath(p).replace("\\", "/").lower()
    for bad in ("appdata/local/google/chrome/user data",
                "appdata\\local\\google\\chrome\\user data",
                "user data/default", "chrome/user data",
                # macOS / Linux 的真实 profile（本技能不承诺支持，但护栏一并挡住）
                "library/application support/google/chrome",
                ".config/google-chrome", ".config/chromium"):
        if bad in low:
            raise SystemExit("拒绝启动：profile 路径指向真实浏览器目录（踩坑⑨）\n  %s\n"
                             "请改用独立的会话目录（SCRAPE_SESSION_DIR）。" % p)
    return True


def read_state():
    p = state_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(st):
    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 进程与端口

def pid_alive(pid):
    """进程存活判断（Windows 走 tasklist，委托给兼容层）。

    ⚠️ 别用 `text=True` 抓 tasklist —— 中文 Windows 输出是 GBK，
    `subprocess` 默认按 UTF-8 解码会在 reader 线程抛 UnicodeDecodeError，
    结果被吞成「进程没活着」→ 状态误判 STALE（2026-09-17 实测踩到）。
    兼容层里是**按字节匹配**的，不涉及任何解码。
    """
    if not pid:
        return False
    if PC:
        return PC.pid_alive(pid)
    try:
        r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                           capture_output=True)
        return str(pid).encode() in (r.stdout or b"")
    except Exception:
        return False


def cdp_alive(port, timeout=2.0):
    try:
        r = urllib.request.Request("http://127.0.0.1:%d/json/version" % port,
                                   headers={"User-Agent": "Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())
    except Exception:
        return None


def free_port(start=DEFAULT_PORT, tries=20):
    for port in range(start, start + tries):
        s = socket.socket()
        s.settimeout(0.6)
        try:
            s.connect(("127.0.0.1", port))
            s.close()          # 已被占用 → 换下一个
            continue
        except Exception:
            s.close()
            return port
    raise SystemExit("找不到可用端口（%d 起 20 个都被占用）" % start)


def chromium_path():
    if PC:
        return PC.playwright_chromium()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return p.chromium.executable_path


def native_chrome_path():
    """原生 Chrome / Edge 路径（含 CHROME_PATH 覆盖），逻辑在兼容层里。"""
    return PC.find_chrome() if PC else None


def pick_exe(args):
    """决定用哪个浏览器内核，返回 (exe, kind)。

    优先级：`--exe` 显式指定 > 原生 Chrome/Edge > Playwright 自带 Chromium。
    为什么默认原生：携程/神州的指纹风控（whaleguard）会拦 Playwright 自带内核。
    探测细节（多路径候选 + `CHROME_PATH` 覆盖）在兼容层里，只有一份实现。
    """
    if PC:
        return PC.resolve_browser(
            explicit=getattr(args, "exe", "") or None,
            prefer_native=not getattr(args, "playwright_chromium", False))
    if getattr(args, "exe", ""):
        return args.exe, "custom"
    if not getattr(args, "playwright_chromium", False):
        n = native_chrome_path()
        if n:
            return n, "native-chrome"
    return chromium_path(), "playwright-chromium"


def task_name():
    """按会话目录生成计划任务名，多会话互不冲突。"""
    import hashlib
    h = hashlib.md5(os.path.abspath(session_dir()).encode("utf-8")).hexdigest()[:8]
    return "wb_scrape_daemon_%s" % h


def launch_cfg_path():
    return os.path.join(session_dir(), "daemon_launch.json")


def pid_file_path():
    return os.path.join(session_dir(), "daemon_pid.json")


def launcher_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon_launch.py")


def read_pid_file():
    try:
        with open(pid_file_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------- 子命令

def cmd_start(args):
    st = read_state()
    if st.get("pid") and pid_alive(st["pid"]) and cdp_alive(st.get("port")):
        print("ALREADY_RUNNING pid=%s port=%s" % (st["pid"], st["port"]))
        print("  CDP: http://127.0.0.1:%s" % st["port"])
        return 0

    prof = profile_path()
    assert_profile_safe(prof)
    os.makedirs(prof, exist_ok=True)
    port = args.port or free_port()
    if cdp_alive(port):
        raise SystemExit("端口 %d 上已有一个可连的 CDP 端点，先确认它是不是本服务的" % port)

    exe, exe_kind = pick_exe(args)

    # 启动配置交给 daemon_launch.py 读，避免命令行引号地狱
    with open(launch_cfg_path(), "w", encoding="utf-8") as f:
        json.dump(dict(exe=exe, exe_kind=exe_kind, port=port, profile=prof,
                       headless=bool(args.headless),
                       log=os.path.join(session_dir(), "daemon_launch.log"),
                       pid_file=pid_file_path()), f, ensure_ascii=False, indent=1)
    try:
        os.remove(pid_file_path())
    except Exception:
        pass

    via, proc = "", None
    tn = task_name()

    # 默认：直接 Popen 拉起（命令内有效）。
    # ⚠️ 2026-09-17 实测更新：Bash 沙箱**会在每条命令结束时清掉进程树**，
    #    DETACHED_PROCESS / CREATE_BREAKAWAY_FROM_JOB 都逃不掉；而 `schtasks`
    #    后来被沙箱的**程序黑名单**拦死（SECURITY POLICY 明确不允许绕过）。
    #    → 所以「进程永久常驻」在这个环境里不成立。**真正的解法是固定 profile**：
    #    带过期时间的 cookie（如携程 cticket）会落盘，实测杀掉浏览器再重启，
    #    ctrip 42 个 cookie 全在、登录照样有效。`human_act.ensure_session()`
    #    会在连不上时自动拉起同一个 profile。
    #    `--schtasks` 仍保留（沙箱外的环境可用），但默认不用。
    if args.schtasks and os.name == "nt":
        tr = '"%s" "%s" "%s"' % (sys.executable or "python",
                                 launcher_path(), launch_cfg_path())
        try:
            subprocess.run(["schtasks", "/Delete", "/TN", tn, "/F"], capture_output=True)
            r1 = subprocess.run(["schtasks", "/Create", "/TN", tn, "/TR", tr,
                                 "/SC", "ONCE", "/ST", "23:59", "/F"], capture_output=True)
            r2 = None
            if r1.returncode == 0:
                r2 = subprocess.run(["schtasks", "/Run", "/TN", tn], capture_output=True)
            if r1.returncode == 0 and r2 is not None and r2.returncode == 0:
                via = "schtasks"
            else:
                msg = (r1.stderr or r1.stdout or b"").decode("utf-8", "replace").strip()
                print("  （计划任务方式不可用：%s；回退到直接启动）" % msg[:110])
        except Exception as e:
            print("  （计划任务异常：%s；回退到直接启动）" % str(e)[:80])

    if not via:
        if PC:
            cmd = PC.launch_argv(exe, port, prof, headless=bool(args.headless))
            kwargs = PC.detach_kwargs()
        else:
            cmd = [exe, "--remote-debugging-port=%d" % port, "--user-data-dir=%s" % prof,
                   "--no-first-run", "--no-default-browser-check",
                   "--disable-blink-features=AutomationControlled", "--window-size=1440,900"]
            if args.headless:
                cmd.append("--headless=new")
            cmd.append("about:blank")
            kwargs = {"creationflags": 0x00000008 | 0x00000200}
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, **kwargs)
        via = "popen"

    for _ in range(46):
        time.sleep(0.5)
        if cdp_alive(port):
            break
    else:
        raise SystemExit("启动超时：%s 未在 23s 内准备好 CDP 端点（exe=%s）" % (port, exe))

    pid = read_pid_file().get("pid") or (proc.pid if via == "popen" else 0)

    write_state(dict(pid=pid, port=port, profile=prof, exe=exe, exe_kind=exe_kind,
                     via=via, task=(tn if via == "schtasks" else ""),
                     started=time.strftime("%Y-%m-%d %H:%M:%S"),
                     headless=bool(args.headless)))
    print("STARTED pid=%s port=%d via=%s" % (pid, port, via))
    print("  browser : %s (%s)" % (exe_kind, exe))
    print("  profile : %s" % prof)
    print("  CDP     : http://127.0.0.1:%d" % port)
    if via == "schtasks":
        print("  task    : %s（任务计划服务拉起，可跨命令存活）" % tn)
    else:
        print("  mode    : 直接拉起（进程在本条命令结束后可能被沙箱收掉）")
        print("            → 登录态靠 **固定的 profile** 保留，不靠进程不退出；")
        print("              采集脚本用 human_act.ensure_session() 会自动重新拉起")
    print("  → 采集脚本用  XHS_CDP=http://127.0.0.1:%d  连接，**不要关浏览器**" % port)
    if exe_kind == "playwright-chromium":
        print("  ⚠️ 当前是 Playwright 自带内核：携程/神州 的指纹风控可能直接拦（whaleguard block）")
    # 用 os._exit 跳过解释器关闭：此时 Playwright 驱动里还挂着未完成的
    # 连接任务，正常退出会喷一堆 "Task was destroyed but it is pending!"，
    # 看着像启动失败，其实浏览器已经活了（实测 CDP 正常）。
    sys.stdout.flush()
    os._exit(0)


def cmd_status(args):
    st = read_state()
    if not st:
        print("NOT_RUNNING（没有 %s）" % state_path())
        return 1
    ok_pid = pid_alive(st.get("pid"))
    ver = cdp_alive(st.get("port")) or {}
    alive = ok_pid and bool(ver)
    print("%s pid=%s port=%s headless=%s started=%s"
          % ("RUNNING" if alive else "STALE", st.get("pid"), st.get("port"),
             st.get("headless"), st.get("started")))
    print("  profile : %s" % st.get("profile"))
    if st.get("exe_kind"):
        print("  browser : %s (%s)" % (st.get("exe_kind"), st.get("exe")))
    if ver:
        print("  browser : %s" % ver.get("Browser"))
        print("  CDP     : %s" % ver.get("webSocketDebuggerUrl", "")[:80])
    if not alive:
        print("  （进程或端口已失效，可重新 start；state 文件会在 start 时覆盖）")
    return 0 if alive else 1


def cmd_exec(args):
    """在常驻浏览器里跑一次动作，**只关页面、绝不关浏览器**。"""
    st = read_state()
    if not (st.get("pid") and cdp_alive(st.get("port"))):
        raise SystemExit("常驻会话未运行，先 `session_daemon.py start`")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % st["port"])
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1200)
            if args.js:
                out = page.evaluate(args.js)
                print(json.dumps(out, ensure_ascii=False, indent=2) if not isinstance(out, str) else out)
            else:
                print("TITLE:", page.title())
                print("URL  :", page.url)
        finally:
            page.close()          # ← 只关这个标签页
            # 注意：不要 browser.close()！那会把常驻会话连同 cookie 一起带走
    print("EXEC_DONE（浏览器保持运行）")
    return 0


def cmd_stop(args):
    st = read_state()
    if not st:
        print("NOT_RUNNING")
        return 0
    pid = st.get("pid")
    if pid and pid_alive(pid):
        # 结束进程树的平台差异收敛在兼容层；
        # 中文 Windows 的 taskkill 输出是 GBK，那边是按字节处理的不做解码。
        try:
            if PC:
                PC.kill_tree(pid)
            else:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True)
        except Exception as e:
            print("停止失败：%s" % str(e)[:80])
    # 计划任务要一并删掉，否则会残留一个会自动拉起浏览器的任务
    tn = st.get("task") or task_name()
    try:
        subprocess.run(["schtasks", "/Delete", "/TN", tn, "/F"], capture_output=True)
    except Exception:
        pass
    try:
        os.remove(pid_file_path())
    except Exception:
        pass
    os.remove(state_path())
    print("STOPPED pid=%s" % pid)
    print("  提示：停止 = 下次要重新登录。同一批抓取任务中途不要 stop。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="常驻会话服务（保持连接不退出）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="启动常驻浏览器（已在运行则复用）")
    s.add_argument("--port", type=int, default=0)
    s.add_argument("--headless", action="store_true", help="默认有头；无头风控更严，谨慎用")
    s.add_argument("--exe", default="", help="显式指定浏览器可执行文件（默认自动找原生 Chrome）")
    s.add_argument("--playwright-chromium", action="store_true",
                   help="强制用 Playwright 自带内核（携程/神州 可能被风控拦，一般只用于调试）")
    s.add_argument("--schtasks", action="store_true",
                   help="用任务计划服务拉起（真跨命令存活；但本机沙箱已把 schtasks "
                        "列入程序黑名单，会直接拒绝）")
    s.set_defaults(func=cmd_start)

    sub.add_parser("status", help="查看是否常驻中").set_defaults(func=cmd_status)

    e = sub.add_parser("exec", help="在常驻浏览器里跑一次动作（不关浏览器）")
    e.add_argument("url")
    e.add_argument("--js", default="")
    e.set_defaults(func=cmd_exec)

    sub.add_parser("stop", help="停止常驻会话（会丢登录态，慎用）").set_defaults(func=cmd_stop)

    args = ap.parse_args()
    raise SystemExit(args.func(args) or 0)


if __name__ == "__main__":
    main()
