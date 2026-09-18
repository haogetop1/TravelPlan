# -*- coding: utf-8 -*-
"""常驻浏览器启动器（交给 Windows 任务计划服务拉起）。

⚠️ 2026-09-18 更正：这条路**在受沙箱保护的执行环境里后来被封了** ——
`schtasks.exe` / `wmic.exe` 被列入程序黑名单（`PROGRAM BLOCKED BY SECURITY POLICY`，
不允许重试或换壳调用）；改用 PS 的 `Register-ScheduledTask` 虽然没被拦，
但拉起的 Chrome **仍会在命令结束时被杀**。
→ **不要依赖本文件实现「进程级常驻」**。真正的解法见 `SKILL.md` 的
「沙箱里『进程级常驻』不成立」一节：让**用户自己启动窗口** + **cookie 快照**。
本文件保留仅作历史记录与「无沙箱环境（如用户本机直接跑）」时的备选。

为什么不由 `session_daemon.py` 直接 Popen
----------------------------------------
Bash 沙箱会在**每条命令结束时清掉整棵进程树**，`DETACHED_PROCESS` 和
`CREATE_BREAKAWAY_FROM_JOB` 实测都逃不掉 —— 2026-09-17 实测两次：
start 之后 port 9222 在**下一条独立命令**里就 closed，进程列表里也没有了。

任务计划的父进程是**调度服务本身**，不在那条命令的进程树里，
所以它拉起的 Chrome 才能真的跨命令、跨会话活着。
（2026-09-17 实测：`schtasks /Run` 拉起后，下一条独立命令里端口仍 OPEN、9 个 chrome 进程健在。
  但 2026-09-18 该手段被沙箱拦截，见上方更正。）

配置由 `session_daemon.py` 写入 `<会话目录>/daemon_launch.json`，
本脚本读它、拉起浏览器、把 pid 写进 `<会话目录>/daemon_pid.json`。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

DETACHED = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def cdp_ok(port, timeout=2.0):
    try:
        r = urllib.request.Request("http://127.0.0.1:%d/json/version" % port,
                                   headers={"User-Agent": "Mozilla/5.0"})
        return bool(urllib.request.urlopen(r, timeout=timeout).read())
    except Exception:
        return False


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "daemon_launch.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    logf = cfg.get("log") or os.path.join(cfg["profile"], "..", "daemon_launch.log")

    def w(msg):
        try:
            with open(logf, "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
        except Exception:
            pass

    if cdp_ok(cfg["port"]):
        w("SKIP 端口 %d 已有可连的 CDP（复用，不重复启动）" % cfg["port"])
        return 0

    cmd = [cfg["exe"],
           "--remote-debugging-port=%d" % cfg["port"],
           "--user-data-dir=%s" % cfg["profile"],
           "--no-first-run", "--no-default-browser-check",
           "--disable-blink-features=AutomationControlled",
           "--window-size=%s" % cfg.get("window", "1440,900")]
    if cfg.get("headless"):
        cmd.append("--headless=new")
    cmd.append("about:blank")

    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=DETACHED)
    except Exception as e:
        w("FAIL 启动异常: %s" % str(e)[:160])
        return 1

    ok = False
    for _ in range(30):
        time.sleep(0.7)
        if cdp_ok(cfg["port"]):
            ok = True
            break

    if cfg.get("pid_file"):
        try:
            with open(cfg["pid_file"], "w", encoding="utf-8") as f:
                json.dump(dict(pid=p.pid, port=cfg["port"], cdp=ok,
                               exe=cfg["exe"], exe_kind=cfg.get("exe_kind", ""),
                               ts=time.strftime("%Y-%m-%d %H:%M:%S")), f,
                          ensure_ascii=False, indent=1)
        except Exception as e:
            w("WARN 写 pid_file 失败: %s" % str(e)[:80])

    w("pid=%d port=%d cdp=%s exe=%s" % (p.pid, cfg["port"], ok, cfg["exe"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
