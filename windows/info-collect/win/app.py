#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py —— InfoCollect 入口

子命令：
    run         前台采集（有控制台，Ctrl+C 停止）
    tray        托盘常驻（无窗口，开机自启用这个）
    stop        让正在运行的托盘实例正常退出
    ui          打开配置界面
    report      看某天的报表（无控制台时自动开窗口）
    status      看运行状态与配置路径
    autostart   开机自启：on / off / status
    config      打印配置文件内容
    upload      手动推送一次待上传数据
    wipe        清空采集数据

用法：
    py -3 -X utf8 app.py                # 前台采集
    py -3 -X utf8 app.py tray           # 托盘常驻
    py -3 -X utf8 app.py ui             # 配置界面
    py -3 -X utf8 app.py report --date 2026-10-30
    py -3 -X utf8 app.py autostart on
    py -3 -X utf8 app.py stop
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import autostart
import config
import reporter
import shutdown
from sampler import Sampler
from store import Store
from uploader import Uploader

APP_TITLE = "InfoCollect"
MUTEX_NAME = "InfoCollect_SingleInstance"
ERROR_ALREADY_EXISTS = 183
CREATE_NO_WINDOW = 0x08000000

_mutex_handle = None      # 必须保住引用，否则可能被回收导致锁失效
_launcher_cmd: list[str] | None = None


# ---------------------------------------------------------------- 基础设施

def setup_console() -> None:
    """让中文在控制台正常输出（不处理会出现乱码）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def setup_logging(verbose: bool = False) -> logging.Logger:
    config.ensure_dir()
    log = logging.getLogger("infocollect")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    if log.handlers:                       # 重复调用时不重复加 handler
        return log

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")

    # 文件日志：必须显式 utf-8，否则中文标题会写成乱码
    fh = RotatingFileHandler(
        config.log_path(), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    log.addHandler(fh)

    # 控制台日志：pythonw 下 sys.stderr 是 None，这时跳过
    if sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.setLevel(logging.DEBUG if verbose else logging.INFO)
        log.addHandler(sh)

    return log


def install_excepthook() -> None:
    """把未捕获异常写进日志。

    --windowed 的 exe 没有控制台，异常默认连一行提示都留不下，用户只看到
    托盘图标消失。日志是事后排查的唯一线索，所以这里兜底记一笔。
    """
    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        try:
            log = setup_logging(False)
            log.error("未捕获异常", exc_info=(exc_type, exc, tb))
        except Exception:
            pass                  # 日志本身失败也不能再抛，否则二次崩溃

    sys.excepthook = hook


def acquire_single_instance() -> bool:
    """命名互斥体做单实例锁。返回 False 表示已经有一个在跑。

    没有这个锁的话：开机自启开一个 + 你手动再开一个 = 同一段时间被记两遍。
    """
    global _mutex_handle
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]

    handle = k32.CreateMutexW(None, 0, MUTEX_NAME)
    if not handle:
        return True                        # 拿不到锁也放行，别把程序卡死
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        k32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _mutex_handle = handle
    return True


def alert(message: str) -> None:
    """没有控制台时（pythonw / windowed exe），print 等于丢掉，只能弹窗。"""
    if sys.stdout is not None:
        print(message)
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x40)
    except Exception:
        pass


def launcher_cmd() -> list[str]:
    """启动本程序另一个实例的命令前缀。

    源码形态用 pythonw（不闪黑框），打包形态直接用 exe 自己。
    只探测一次并缓存——pick_interpreter 会起子进程，不能每次点菜单都探。
    """
    global _launcher_cmd
    if _launcher_cmd is None:
        if autostart.is_frozen():
            _launcher_cmd = [sys.executable]
        else:
            python, _ = autostart.pick_interpreter()
            _launcher_cmd = [python, str(Path(__file__).resolve())]
    return _launcher_cmd


def spawn(*args: str) -> None:
    """开一个独立的界面进程（报表 / 配置）。不能在本进程里开 tkinter 窗口，
    因为托盘的消息循环占着主线程。"""
    subprocess.Popen(
        launcher_cmd() + list(args),
        close_fds=True,
        creationflags=CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )


def icon_path() -> Path | None:
    p = autostart.program_dir() / "infocollect.ico"
    try:
        import icon as icon_mod
        return icon_mod.ensure_icon(p)
    except Exception:
        return p if p.exists() else None


# ---------------------------------------------------------------- 子命令

def cmd_run(verbose: bool) -> int:
    log = setup_logging(verbose)

    if not acquire_single_instance():
        print("已经有一个 InfoCollect 在运行了（单实例锁）。")
        print("如果想重启，先结束掉已有的那个进程。")
        return 1

    cfg = config.load()
    store = Store(config.db_path())

    up = Uploader(cfg, store, log)
    log.info("InfoCollect v%s 启动（%s），上报状态：%s",
             config.APP_VERSION, "打包 exe" if autostart.is_frozen() else "源码",
             up.status_text())

    sampler = Sampler(cfg, store, log, uploader=up)

    # 关机 / 注销 / 关闭控制台窗口时收尾：结算 + 最后推一次
    ok = shutdown.install(
        lambda reason: sampler.shutdown(shutdown.EVENT_NAMES.get(reason, reason))
    )
    if ok:
        log.info("已注册退出回调（关机/注销时结算并尝试推送）")
    else:
        log.info("未注册退出回调：当前进程没有控制台，关机会被直接终止（数据仍靠启动补传兜底）")

    try:
        sampler.run_forever()
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在结算并退出…")
        log.info("收到 KeyboardInterrupt")
    finally:
        store.close()
    return 0


def _cfg_mtime() -> float:
    try:
        return config.config_path().stat().st_mtime
    except OSError:
        return 0.0


def _quick_stats() -> dict:
    """给菜单/提示条用的即时统计。开独立连接，避免和采样线程抢同一把锁。"""
    out = {"total": 0, "rows": 0, "pending": 0, "ok": False}
    try:
        st = Store(config.db_path())
        try:
            data = reporter.collect(st, date.today())
            out["total"] = data["total"]
            out["rows"] = len(data["rows"])
            out["pending"] = st.pending_count()
            out["ok"] = True
        finally:
            st.close()
    except Exception:
        pass
    return out


def cmd_tray(verbose: bool) -> int:
    """无窗口常驻：采样跑在后台线程，主线程跑托盘消息循环。

    为什么不把采样也放主线程：托盘的窗口消息循环必须占住主线程
    （Win32 的窗口和消息队列绑定在创建它的线程上），而采样是个死循环，
    两者只能分线程。这也是为什么要给 Store 加 RLock 和 check_same_thread=False。
    """
    log = setup_logging(verbose)

    if not acquire_single_instance():
        alert("InfoCollect 已经在运行了。\n\n看屏幕右下角的托盘图标（可能在 ^ 展开区里）。")
        return 1

    import tray as tray_mod

    cfg = config.load()
    store = Store(config.db_path())
    up = Uploader(cfg, store, log)
    log.info("InfoCollect v%s 托盘模式启动（%s），上报状态：%s",
             config.APP_VERSION, "打包 exe" if autostart.is_frozen() else "源码",
             up.status_text())

    sampler = Sampler(cfg, store, log, uploader=up)

    def worker() -> None:
        try:
            sampler.run_forever()
        except Exception:
            log.exception("采样线程异常退出")

    thread = threading.Thread(target=worker, name="sampler", daemon=True)
    thread.start()

    # 关机/注销：无控制台的进程收不到 SetConsoleCtrlHandler 回调，
    # 所以托盘窗口自己接 WM_QUERYENDSESSION（见 tray.py）。
    # 控制台那条路也在装，两套都装上不冲突：谁先触发算谁，_finalize 只跑一次。
    ok = shutdown.install(
        lambda reason: sampler.shutdown(shutdown.EVENT_NAMES.get(reason, reason))
    )
    if ok:
        log.info("已注册控制台退出回调")

    def on_endsession(kind: str) -> None:
        log.info("收到系统关机/注销通知（%s），开始收尾", kind)
        sampler.shutdown("系统关机" if kind == "query" else "会话结束")

    state = {"mtime": _cfg_mtime(), "paused": False, "auto": autostart.diagnose()}

    def autostart_warning() -> tuple[str, str, int] | None:
        """启动时体检一次开机自启，返回 (标题, 说明, 图标) 或 None。

        自启失效是**静默**的：注册表里指向的文件被移动/删除后，开机不会
        有任何报错，只能等到第二天发现没数据。所以启动时主动查一遍。
        """
        info = state["auto"]
        if info["enabled"]:
            if info["stale"]:
                return ("开机自启已失效",
                        "注册表指向的程序文件不存在（可能移动过目录）。\n"
                        "右键托盘图标 → 开机自启：路径已失效，点此修复。", 0x02)
            if info["command"] != info["expected"]:
                return ("开机自启指向旧位置",
                        "右键托盘图标 → 开机自启：路径已失效，点此修复。", 0x02)
        elif cfg.get("autostart"):
            return ("开机自启未生效",
                    "配置里记录为开启，但注册表里没有这一项。\n"
                    "右键托盘图标 → 开机自启 可重新写入。", 0x02)
        return None

    # ---------------------------------------------------------- 动作

    def tooltip_text() -> str:
        st = _quick_stats()
        head = "已暂停" if state["paused"] else "今日"
        return f"InfoCollect · {head} {reporter.fmt_duration(st['total'])}"

    def do_push() -> None:
        def work() -> None:
            n = up.push_once()
            tray_obj.refresh_tooltip(tooltip_text())
            if n:
                tray_obj.notify("推送完成", f"已上传 {n} 条会话")
            else:
                tray_obj.notify("没有可推的数据", "或推送失败，详情见日志")
        threading.Thread(target=work, daemon=True).start()

    def toggle_pause() -> None:
        if state["paused"]:
            sampler.resume()
            state["paused"] = False
        else:
            sampler.pause()
            state["paused"] = True
        tray_obj.refresh_tooltip(tooltip_text())

    def toggle_autostart() -> None:
        want = not autostart.is_enabled()
        ok, msg = autostart.set_enabled(want)
        if not ok:
            tray_obj.notify("自启设置失败", msg, 0x03)
            return
        new_cfg = config.load()
        new_cfg["autostart"] = want
        config.save(new_cfg)
        state["auto"] = autostart.diagnose()
        log.info("开机自启已%s", "开启" if want else "关闭")
        tray_obj.notify("开机自启已开启" if want else "开机自启已关闭",
                        "下次登录 Windows 会自动启动。" if want else "")

    def repair_autostart() -> None:
        """把注册表里的自启命令重写成"当前这个程序"，修好移动目录后的失效项。"""
        ok, msg = autostart.set_enabled(True)
        if not ok:
            tray_obj.notify("自启修复失败", msg, 0x03)
            return
        cfg["autostart"] = True
        config.save(cfg)
        state["auto"] = autostart.diagnose()
        log.info("开机自启已修复：%s", msg)
        tray_obj.notify("开机自启已修复", "下次登录 Windows 会从这个位置启动。")

    def open_dir() -> None:
        config.ensure_dir()
        os.startfile(str(config.app_dir()))

    def do_quit() -> None:
        log.info("从托盘菜单退出")
        sampler.shutdown("托盘菜单退出")
        tray_obj.stop()

    def build_menu() -> list:
        st = _quick_stats()
        items = [
            tray_mod.Item(f"今日活跃：{reporter.fmt_duration(st['total'])}（{st['rows']} 段）", None),
        ]
        if (cfg.get("upload") or {}).get("enabled"):
            items.append(tray_mod.Item(
                f"待上传：{st['pending']} 条" if st["pending"] else "待上传：0 条（已同步）", None))
        else:
            items.append(tray_mod.Item("上报：已关闭，数据只存本机", None))

        items += [
            tray_mod.sep(),
            tray_mod.Item("查看今日报表", lambda: spawn("report", "--window")),
            tray_mod.Item("打开配置界面", lambda: spawn("ui")),
            tray_mod.Item("立即推送", do_push, enabled=up.ready and st["pending"] > 0),
            tray_mod.sep(),
            tray_mod.Item("已暂停采集（点击恢复）" if state["paused"] else "暂停采集",
                          toggle_pause, checked=state["paused"]),
            (tray_mod.Item("开机自启：路径已失效，点此修复", repair_autostart)
             if state["auto"]["enabled"]
             and (state["auto"]["stale"] or state["auto"]["command"] != state["auto"]["expected"])
             else tray_mod.Item("开机自启", toggle_autostart,
                                checked=state["auto"]["enabled"])),
            tray_mod.Item("打开数据目录", open_dir),
            tray_mod.sep(),
            tray_mod.Item(f"InfoCollect v{config.APP_VERSION}", None),
            tray_mod.Item("退出", do_quit),
        ]
        return items

    # ---------------------------------------------------------- 定时任务

    def on_timer() -> None:
        # ① 配置文件变了就热更新（配置窗口保存后靠这个生效，不用重启）
        m = _cfg_mtime()
        if m and m != state["mtime"]:
            state["mtime"] = m
            try:
                fresh = config.load()
                cfg.clear()
                cfg.update(fresh)
                sampler.apply_config(cfg)
                up.apply_config(cfg)
                state["auto"] = autostart.diagnose()
                log.info("检测到配置文件变化，已热更新")
            except Exception:
                log.exception("配置热更新失败")
        # ② 刷新托盘提示
        tray_obj.refresh_tooltip(tooltip_text())

    def on_start() -> None:
        """托盘图标挂上之后立刻做一次自启体检（这时才能弹通知）。"""
        warn = autostart_warning()
        if warn:
            log.warning("开机自启体检：%s（注册表当前值：%s）",
                        warn[0], state["auto"]["command"] or "(未写入)")
            tray_obj.notify(warn[0], warn[1], warn[2])

    tray_obj = tray_mod.Tray(
        tooltip=tooltip_text(),
        menu=build_menu,
        icon_path=icon_path(),
        log=log,
        on_timer=on_timer,
        on_endsession=on_endsession,
        on_start=on_start,
    )
    tray_obj.set_timer(30_000)

    try:
        rc = tray_obj.run()
    finally:
        sampler.shutdown("托盘循环结束")
        thread.join(timeout=8)
        store.close()
    log.info("已退出")
    return rc


def cmd_ui(args) -> int:
    import ui_config
    return ui_config.show()


def cmd_autostart(args) -> int:
    if args.state == "status":
        info = autostart.diagnose()
        print(f"运行形态：{'打包 exe' if info['frozen'] else '源码 + 解释器'}")
        print(f"打包产物：{info['exe'] or '(没找到 exe)'}")
        print(f"状态：{'已启用' if info['enabled'] else '未启用'}")
        print(f"应写命令：{info['expected']}")
        if info["enabled"]:
            print(f"当前命令：{info['command']}")
            if info["stale"]:
                print("⚠ 命令里的路径已不存在，自启会静默失败。重新执行 on 可修复。")
            elif info["command"] != info["expected"]:
                print("⚠ 与当前程序位置不一致（可能移动过目录）。重新执行 on 可修复。")
        return 0

    want = args.state == "on"
    mode = "python" if getattr(args, "python", False) else "auto"
    ok, msg = autostart.set_enabled(want, mode)
    if not ok:
        print(f"失败：{msg}")
        return 1

    cfg = config.load()
    cfg["autostart"] = want
    config.save(cfg)

    if want:
        print("已开启开机自启（仅当前用户，无需管理员）：")
        print(f"  HKCU\\{autostart.REG_RUN}\\{autostart.VALUE_NAME}")
        print(f"  = {msg}")
        print()
        print("下次登录 Windows 时会自动以托盘方式启动。")
        print("想立刻试一下：先关掉当前进程，再双击 start_silent.bat")
    else:
        print(f"已关闭开机自启（{msg}）")
    return 0


def cmd_stop(args) -> int:
    """让正在运行的托盘实例自己退出（走正常收尾：结算 + 推送 + 删图标）。

    做法是找到托盘那个隐藏窗口，给它发 WM_CLOSE。它收到后销毁窗口，
    消息循环结束，run() 的 finally 会做收尾——比 taskkill 干净得多，
    强杀会留下"未结算会话"，下次启动才补上。
    """
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.c_size_t, ctypes.c_ssize_t]

    hwnd = user32.FindWindowW("InfoCollectTrayWnd", None)
    if not hwnd:
        print("没有找到正在运行的托盘实例。")
        print("（如果是用 `app.py run` 前台跑的，在那个窗口按 Ctrl+C 退出）")
        return 1
    user32.PostMessageW(hwnd, 0x0010, 0, 0)      # WM_CLOSE
    print("已发送退出请求，正在结算并推送…")
    return 0


def cmd_report(args) -> int:
    day = date.today()
    if args.date:
        try:
            day = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"日期格式不对：{args.date}，应为 YYYY-MM-DD")
            return 1

    # 打包成 --windowed 的 exe 时没有控制台可打印，这时改用窗口显示。
    # 注意不能只判断 sys.stdout is None：从终端启动 pythonw 时 stdout 依然
    # 是继承来的管道，所以托盘菜单那边会显式传 --window。
    if args.window or sys.stdout is None:
        import ui_report
        return ui_report.show(day)

    if not config.db_path().exists():
        print(f"还没有数据文件：{config.db_path()}")
        print("先跑一次采集：py -3 -X utf8 app.py")
        return 1

    store = Store(config.db_path())
    try:
        print(reporter.render(store, day, tail=args.tail))
    finally:
        store.close()
    return 0


def cmd_upload(args) -> int:
    """手动推送一次。用于测试端点是否通、以及补推积压数据。"""
    log = setup_logging(True)
    cfg = config.load()

    if not config.db_path().exists():
        print(f"还没有数据文件：{config.db_path()}")
        return 1

    store = Store(config.db_path())
    try:
        up = Uploader(cfg, store, log)
        print(f"上报状态：{up.status_text()}")
        print(f"待上传：{store.pending_count()} 条")

        if not up.ready:
            print()
            print("未启用或 endpoint 为空，未执行推送。")
            print("编辑配置文件后重试：py -3 -X utf8 app.py config")
            return 0

        if args.dry_run:
            items = store.pending_sessions(up.batch_size)
            if not items:
                print("没有待上传的已结算会话。")
                return 0
            payload = up.build_payload(items)
            print()
            print("[dry-run] 将发送这样的 JSON：")
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            print(text[:1500] + ("\n…（已截断）" if len(text) > 1500 else ""))
            return 0

        n = up.push_once()
        if n:
            print(f"✅ 推送成功：{n} 条")
            return 0
        print("❌ 推送失败或没有可推的数据，详见日志：")
        print(f"   {config.log_path()}")
        return 1
    finally:
        store.close()


def cmd_cloud(args) -> int:
    """检查云端配置是否可用。填完 Supabase 的 URL 和 key 之后先跑这个。

    `--ping` 会真的发一个只读请求过去，把"地址通不通 / 密钥对不对 / 权限够不够"
    三件事分开报告——比等采集跑一天才发现推不上去强得多。
    """
    log = setup_logging(False)
    cfg = config.load()
    store = Store(config.db_path()) if config.db_path().exists() else None
    try:
        up = Uploader(cfg, store, log)

        print(f"上报状态：{'启用' if up.enabled else '关闭'}")
        print(f"服务端类型：{up.provider}")
        print(f"实际地址：{up.url() or '(未填)'}")
        tok = up.token
        print(f"密钥：{'(未填)' if not tok else tok[:6] + '…' + tok[-4:] if len(tok) > 12 else '已填'}")
        print(f"超时：{up.timeout:.0f} 秒　批量：{up.batch_size} 条　"
              f"推送标题：{'是' if up.include_title else '否'}")
        if store:
            print(f"本机标识：{store.device_id()}　机器名：{up.hostname}　"
                  f"显示名：{store.device_label() or '(未设置)'}")
            print(f"待上传：{store.pending_count()} 条")

        if not up.ready:
            print()
            print("还没配好，先填 endpoint 和 token（见 supabase/setup.md）。")
            return 1

        if args.dry_run:
            items = store.pending_sessions(up.batch_size) if store else []
            if not items:
                print("\n没有待上传的已结算会话，用一节真实数据看看格式：")
                items = [{"id": 1, "start_ts": int(time.time()) - 600,
                          "end_ts": int(time.time()), "app": "code.exe",
                          "category": "编码", "title": "示例 - Visual Studio Code",
                          "device_id": store.device_id() if store else "demo"}]
            payload = up.build_payload(items)
            print("\n[dry-run] 将发送这样的 JSON：")
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            print(text[:1200] + ("\n…（已截断）" if len(text) > 1200 else ""))
            if up.provider == "supabase":
                print("\n请求头：")
                for k, v in up._headers().items():
                    print(f"  {k}: {'<anon key>' if k == 'apikey' else v[:60]}")
            return 0

        if not args.ping:
            return 0

        # ---- 探测
        # 为什么不用 GET /rest/v1/（OpenAPI 根）：
        #   新版 Supabase 要求这个端点用 secret key，publishable key 一律 401
        #   "Secret API key required"，看着像故障、其实一切正常。
        # 改成 POST {"rows": []}：一行都不写，却一次性验证了
        #   地址对不对、密钥被不被接受、函数在不在、anon 有没有 execute 权限。
        url = up.url()
        if up.provider == "supabase":
            print(f"\n上报地址：{url}")
            print("（空数据试调一次函数，不写入任何行）")
            req = urllib.request.Request(
                url, data=json.dumps({"rows": []}).encode("utf-8"),
                headers=up._headers(), method="POST")
        else:
            print(f"\n正在探测 {url} …")
            req = urllib.request.Request(url, headers=up._headers(), method="GET")

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=up.timeout) as resp:
                back = ""
                if up.provider == "supabase":
                    try:
                        back = resp.read(200).decode("utf-8", "replace")
                    except Exception:
                        back = ""
                print(f"✅ HTTP {resp.status}　耗时 {int((time.time()-t0)*1000)} ms"
                      + (f"　返回 {back}" if back else ""))
                print("   地址可达、密钥被接受、函数可执行。可以真推了：app.py upload")
                return 0
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            print(f"⚠ HTTP {e.code} {e.reason}　{body}")
            low = body.lower()
            if e.code == 404 or "pgrst202" in low:
                print("   → 函数不存在。到 SQL Editor 跑 supabase/push_fn.sql（只补函数那段），")
                print("     或者整段重跑 supabase/schema.sql（幂等，不会重复建）。")
            elif e.code in (401, 403):
                print("   → 密钥不对，或者 anon 没有 execute 权限")
                print("     （schema.sql 末尾的 grant execute 那两行漏了？）")
            elif e.code == 400:
                print("   → 参数名对不上：函数必须是 push_sessions(rows jsonb)")
            return 1
        except Exception as e:
            print(f"❌ 连不上：{type(e).__name__}: {e}")
            print("   → 检查网络、代理，或者地址拼错了")
            return 1
    finally:
        if store:
            store.close()


def cmd_device(args) -> int:
    """给这台机器起个名字，云端报表里用它区分多台电脑。"""
    if not config.db_path().exists():
        print(f"还没有数据文件：{config.db_path()}")
        return 1
    store = Store(config.db_path())
    try:
        if args.label is not None:
            store.set_device_label(args.label)
            cfg = config.load()
            cfg["device_label"] = args.label
            config.save(cfg)
        print(f"本机标识：{store.device_id()}")
        print(f"机器名：{socket.gethostname()}")
        print(f"显示名：{store.device_label() or '(未设置，报表里会退回用机器名)'}")
        if args.label is not None:
            print()
            print("已保存。下次推送开始生效；已经推上去的历史行不会改。")
    finally:
        store.close()
    return 0


def cmd_status(args) -> int:
    cfg = config.load()
    print(f"版本：InfoCollect v{config.APP_VERSION}"
          f"（{'打包 exe' if autostart.is_frozen() else '源码'}）")
    print(f"配置目录：{config.app_dir()}")
    print(f"配置文件：{config.config_path()}  {'✓ 存在' if config.config_path().exists() else '✗ 缺失'}")
    print(f"数据文件：{config.db_path()}  {'✓ 存在' if config.db_path().exists() else '✗ 缺失'}")
    print(f"日志文件：{config.log_path()}")
    print()
    print(f"采样间隔：{cfg['sample_interval_seconds']} 秒")
    print(f"闲置阈值：{cfg['idle_threshold_seconds']} 秒")
    print(f"采集标题：{'开' if cfg.get('collect_window_title') else '关'}"
          f"（黑名单 {len(cfg.get('title_blacklist') or [])} 条）")

    auto = autostart.diagnose()
    if auto["enabled"]:
        tip = ""
        if auto["stale"]:
            tip = "  ⚠ 路径已失效，重新执行 autostart on 可修复"
        elif auto["command"] != auto["expected"]:
            tip = "  ⚠ 与当前位置不一致，重新执行 autostart on 可修复"
        print(f"开机自启：已启用{tip}")
    else:
        print("开机自启：未启用（app.py autostart on 可开启）")
    if auto["missing_tk"]:
        print("  ⚠ 没找到带 tkinter 的解释器，配置界面打不开")

    u = cfg.get("upload") or {}
    if not u.get("enabled"):
        print("上报：已关闭")
    elif not str(u.get("endpoint") or "").startswith(("http://", "https://")):
        print("上报：已启用，但 endpoint 无效或为空")
    else:
        prov = "Supabase" if str(u.get("provider") or "").lower() == "supabase" else "自定义"
        print(f"上报：{prov}，每 {float(u.get('interval_hours') or 4):.1f} 小时 → {u['endpoint']}"
              f"（关机推送：{'开' if u.get('on_shutdown', True) else '关'}，"
              f"窗口标题：{'传' if u.get('include_title') else '不传'}）")

    if not config.db_path().exists():
        print()
        print("还没有采集数据。")
        return 0

    store = Store(config.db_path())
    try:
        hb = store.last_heartbeat()
        now = int(datetime.now().timestamp())
        print()
        print(f"累计会话：{store.total_sessions()} 段")
        print(f"设备标识：{store.device_id()}　机器名：{socket.gethostname()}"
              f"　显示名：{store.device_label() or '(未设置)'}")
        pending = store.pending_count()
        if pending:
            print(f"待上传：{pending} 条")
        if hb:
            ago = now - hb
            state = "运行中" if ago <= max(60, cfg["sample_interval_seconds"] * 3) else "未运行"
            print(f"最后心跳：{datetime.fromtimestamp(hb).strftime('%Y-%m-%d %H:%M:%S')}"
                  f"（{ago} 秒前，{state}）")
        else:
            print("最后心跳：无（还没成功采集过）")

        data = reporter.collect(store, date.today())
        print(f"今日活跃：{reporter.fmt_duration(data['total'])}"
              f"（{len(data['rows'])} 段）")
    finally:
        store.close()
    return 0


def cmd_config(args) -> int:
    cfg = config.load()
    print(f"配置文件：{config.config_path()}")
    print("（改完保存即可生效，重新启动采集后读取）")
    print()
    import json

    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    return 0


def cmd_wipe(args) -> int:
    if not config.db_path().exists():
        print("没有数据文件，无需清理。")
        return 0
    if not args.yes:
        n = 0
        store = Store(config.db_path())
        try:
            n = store.total_sessions()
        finally:
            store.close()
        ans = input(f"确定要删除全部 {n} 段记录吗？此操作不可恢复 [y/N] ").strip().lower()
        if ans != "y":
            print("已取消。")
            return 0

    store = Store(config.db_path())
    try:
        store.wipe()
        print("已清空采集数据。")
    finally:
        store.close()
    return 0


# ---------------------------------------------------------------- 入口

def main() -> int:
    setup_console()
    install_excepthook()

    parser = argparse.ArgumentParser(
        description="InfoCollect —— 记录时间都花在哪了",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="开始采集（前台，Ctrl+C 停止）")
    p_run.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")

    p_tray = sub.add_parser("tray", help="托盘常驻（开机自启用这个）")
    p_tray.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")

    sub.add_parser("ui", help="打开配置界面")
    sub.add_parser("stop", help="让正在运行的托盘实例退出")
    p_report = sub.add_parser("report", help="查看某天的报表（无控制台时自动开窗口）")
    p_report.add_argument("--date", help="日期，格式 YYYY-MM-DD，默认今天")
    p_report.add_argument("--tail", type=int, default=10, help="明细显示几段，默认 10")
    p_report.add_argument("--window", action="store_true", help="强制用窗口显示")
    sub.add_parser("status", help="查看运行状态")
    sub.add_parser("config", help="查看配置")
    p_auto = sub.add_parser("autostart", help="开机自启：on / off / status")
    p_auto.add_argument("state", nargs="?", default="status", choices=["on", "off", "status"])
    p_auto.add_argument("--python", action="store_true",
                        help="强制写成源码形态（pythonw + app.py），改代码调试时用")
    p_up = sub.add_parser("upload", help="手动推送一次待上传数据")
    p_up.add_argument("--dry-run", action="store_true", help="只打印将要发送的 JSON，不真的发")
    p_cloud = sub.add_parser("cloud", help="检查云端配置与连通性")
    p_cloud.add_argument("--ping", action="store_true", help="发只读请求，测试地址与密钥")
    p_cloud.add_argument("--dry-run", action="store_true", help="只打印将要发送的 JSON")
    p_dev = sub.add_parser("device", help="查看或设置本机显示名（多设备区分用）")
    p_dev.add_argument("--label", help="设置显示名，如：台式机 / 家里的笔记本")
    p_wipe = sub.add_parser("wipe", help="清空所有采集数据")
    p_wipe.add_argument("--yes", action="store_true", help="跳过确认")

    args = parser.parse_args()

    if os.name != "nt":
        print("本程序只支持 Windows。")
        return 1

    if args.cmd is None:
        # 双击 exe 时没有任何参数。打包形态必须进托盘——否则会变成一个
        # 没有窗口、没有托盘、也关不掉的隐形进程（--windowed 连控制台都没有）。
        if autostart.is_frozen():
            # 首次运行：配置文件还不存在。这时直接进托盘，用户看到的是"点了没反应"，
            # 所以先把配置窗推出来，填完（或关掉）再进托盘。
            if not config.config_path().exists():
                try:
                    import ui_config
                    ui_config.show(first_run=True)
                except Exception:
                    pass          # 界面起不来也不能挡住采集
            return cmd_tray(False)
        return cmd_run(False)
    if args.cmd == "run":
        return cmd_run(getattr(args, "verbose", False))
    if args.cmd == "tray":
        return cmd_tray(getattr(args, "verbose", False))
    if args.cmd == "ui":
        return cmd_ui(args)
    if args.cmd == "stop":
        return cmd_stop(args)
    if args.cmd == "report":
        return cmd_report(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "config":
        return cmd_config(args)
    if args.cmd == "autostart":
        return cmd_autostart(args)
    if args.cmd == "upload":
        return cmd_upload(args)
    if args.cmd == "cloud":
        return cmd_cloud(args)
    if args.cmd == "device":
        return cmd_device(args)
    if args.cmd == "wipe":
        return cmd_wipe(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
