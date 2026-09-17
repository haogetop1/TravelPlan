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

用法
----
  python session_daemon.py start [--port 9222] [--headless]
  python session_daemon.py status
  python session_daemon.py exec <url> [--js "<expression>"]
  python session_daemon.py stop

  # 采集脚本侧（推荐）：把 CDP 端点交给脚本，脚本内部连常驻浏览器
  export XHS_CDP=http://127.0.0.1:9222

文件
----
  会话目录（默认 <cwd>/.workbuddy，可用 SCRAPE_SESSION_DIR 覆盖）
    ├── browser_profile/         # 持久化 profile（cookie 落盘的那部分）
    └── session_daemon.json      # {pid, port, profile, started}
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

DEFAULT_PORT = 9222


# ---------------------------------------------------------------- 路径与安全

def session_dir():
    d = os.environ.get("SCRAPE_SESSION_DIR") or os.path.join(os.getcwd(), ".workbuddy")
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
    """
    low = os.path.abspath(p).replace("\\", "/").lower()
    for bad in ("appdata/local/google/chrome/user data",
                "appdata\\local\\google\\chrome\\user data",
                "user data/default", "chrome/user data"):
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
    """进程存活判断。

    ⚠️ 别用 `text=True` 抓 tasklist —— 中文 Windows 输出是 GBK，
    `subprocess` 默认按 UTF-8 解码会在 reader 线程抛 UnicodeDecodeError，
    结果被吞成「进程没活着」→ 状态误判 STALE（2026-09-17 实测踩到）。
    这里直接按字节匹配 ASCII 数字，不涉及任何解码。
    """
    if not pid:
        return False
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                               capture_output=True)
            return str(pid).encode() in (r.stdout or b"")
        os.kill(pid, 0)
        return True
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
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return p.chromium.executable_path


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

    exe = chromium_path()
    cmd = [
        exe,
        "--remote-debugging-port=%d" % port,
        "--user-data-dir=%s" % prof,
        "--no-first-run", "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1440,900",
    ]
    if args.headless:
        cmd.append("--headless=new")
    cmd.append("about:blank")

    kwargs = {}
    if os.name == "nt":
        # 脱离父进程：脚本退出后浏览器继续活着（这正是常驻的意义）
        kwargs["creationflags"] = 0x00000008 | 0x00000200   # DETACHED | NEW_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)

    for _ in range(30):
        time.sleep(0.5)
        if cdp_alive(port):
            break
    else:
        raise SystemExit("启动超时：%s 未在 15s 内准备好 CDP 端点（exe=%s）" % (port, exe))

    write_state(dict(pid=proc.pid, port=port, profile=prof, exe=exe,
                     started=time.strftime("%Y-%m-%d %H:%M:%S"),
                     headless=bool(args.headless)))
    print("STARTED pid=%d port=%d" % (proc.pid, port))
    print("  profile : %s" % prof)
    print("  CDP     : http://127.0.0.1:%d" % port)
    print("  → 采集脚本用  XHS_CDP=http://127.0.0.1:%d  连接，**不要关浏览器**" % port)
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
        try:
            if os.name == "nt":
                # 同 pid_alive：中文 Windows 的 taskkill 输出是 GBK，
                # 别用 text=True（会抛 UnicodeDecodeError）
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True)
            else:
                os.kill(pid, 15)
        except Exception as e:
            print("停止失败：%s" % str(e)[:80])
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
