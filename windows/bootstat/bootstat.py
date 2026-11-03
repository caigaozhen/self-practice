#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BootStat —— Windows 开机小助手（单文件、零第三方依赖）

功能：
  1. --install : 把自己写进 HKCU 的 Run 注册表键，实现开机自启（无需管理员）
  2. 每次开机/登录后自动记录一次：开机时刻、启动耗时
  3. 弹窗展示统计结果，几秒后自动消失（不打扰你干活）

用法：
  python bootstat.py --install     安装自启动（可重复执行，幂等）
  python bootstat.py --uninstall   移除自启动
  python bootstat.py --status      在命令行看统计（不开弹窗）
  python bootstat.py --run         记录一次并弹窗（不带参数时默认就是它）
  python bootstat.py --run --no-popup   只记录，不弹窗
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

APP_NAME = "BootStat"
APP_TITLE = "开机小助手"
REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
MAX_RECORDS = 366  # 最多保留一年的记录

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.GetTickCount64.restype = ctypes.c_ulonglong  # 默认返回 c_int 会溢出，必须显式声明


# ---------------------------------------------------------------- 路径与数据

def data_dir() -> Path:
    """数据目录，默认 %LOCALAPPDATA%\\BootStat（可用 BOOTSTAT_HOME 覆盖）"""
    override = os.environ.get("BOOTSTAT_HOME")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def data_file() -> Path:
    return data_dir() / "boots.json"


def load_data() -> dict:
    path = data_file()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("boots"), list):
                return raw
        except Exception:
            pass  # 文件损坏就当空数据，不阻断启动
    return {"boots": []}


def save_data(data: dict) -> None:
    path = data_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- 时间计算

def uptime_seconds() -> float:
    """系统已运行的秒数（从本次开机算起）"""
    try:
        return _k32.GetTickCount64() / 1000.0
    except Exception:
        return 0.0


def current_boot_at() -> datetime:
    """反推本次开机时刻 = 现在 - 已运行时长"""
    return datetime.now() - timedelta(seconds=uptime_seconds())


def human_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} 秒"
    return f"{seconds // 60} 分 {seconds % 60:02d} 秒"


def minutes_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def fmt_minutes(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


# ---------------------------------------------------------------- 记录

def record_boot(data: dict) -> tuple[dict, bool]:
    """记录本次开机。同一次开机重复运行会自动去重（按分钟判定）。"""
    boot_at = current_boot_at()
    key = boot_at.strftime("%Y-%m-%d %H:%M")

    for rec in reversed(data["boots"][-20:]):
        if rec.get("key") == key:
            return rec, False

    rec = {
        "key": key,
        "boot_at": boot_at.strftime("%Y-%m-%d %H:%M:%S"),
        "startup_seconds": round(uptime_seconds(), 1),
        "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    data["boots"].append(rec)
    data["boots"] = data["boots"][-MAX_RECORDS:]
    save_data(data)
    return rec, True


def build_summary(data: dict, rec: dict) -> list[str]:
    """把统计结果拼成几行文字，弹窗和命令行共用"""
    boots = data["boots"]
    boot_at = datetime.strptime(rec["boot_at"], "%Y-%m-%d %H:%M:%S")
    lines = [
        f"本次开机：{boot_at.month}月{boot_at.day}日 {boot_at.strftime('%H:%M')}"
        f"　（累计第 {len(boots)} 次记录）",
        f"启动耗时：约 {human_duration(rec.get('startup_seconds', 0))}"
        "（开机 → 本程序启动）",
    ]

    recent = boots[-7:]
    if len(recent) >= 2:
        avg = round(sum(minutes_of_day(datetime.strptime(b["boot_at"], "%Y-%m-%d %H:%M:%S"))
                        for b in recent) / len(recent))
        lines.append(f"最近 {len(recent)} 次平均 {fmt_minutes(avg)} 开机")

    if len(boots) >= 2:
        prev = datetime.strptime(boots[-2]["boot_at"], "%Y-%m-%d %H:%M:%S")
        diff = minutes_of_day(boot_at) - minutes_of_day(prev)
        if diff == 0:
            word = "和上次几乎一样"
        elif diff > 0:
            word = f"比上次晚了 {diff} 分钟"
        else:
            word = f"比上次早了 {-diff} 分钟"
        lines.append(f"{word}（上次 {prev.month}月{prev.day}日 {prev.strftime('%H:%M')}）")

    return lines


# ---------------------------------------------------------------- 界面

def msgbox(text: str, icon: int = 0x40) -> None:
    ctypes.windll.user32.MessageBoxW(0, text, APP_TITLE, icon)


def show_popup(lines: list[str], seconds: int = 8) -> None:
    """右下角小弹窗，倒计时自动关闭；tkinter 不可用时退回系统 MessageBox"""
    try:
        import tkinter as tk
    except Exception:
        msgbox("\n".join(lines))
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    try:
        root = tk.Tk()
    except Exception:
        msgbox("\n".join(lines))
        return

    bg = "#FFFFFF"
    root.title(APP_TITLE)
    root.configure(bg=bg)
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    pad = 20
    tk.Frame(root, bg="#2563EB", height=3).pack(fill="x")
    tk.Label(root, text=APP_TITLE, font=("Microsoft YaHei UI", 12, "bold"),
             bg=bg, fg="#111827").pack(anchor="w", padx=pad, pady=(14, 8))

    body = tk.Frame(root, bg=bg)
    body.pack(anchor="w", padx=pad)
    for text in lines:
        tk.Label(body, text=text, font=("Microsoft YaHei UI", 9), bg=bg, fg="#374151",
                 justify="left", anchor="w").pack(anchor="w", pady=2)

    footer = tk.Frame(root, bg=bg)
    footer.pack(fill="x", padx=pad, pady=(12, 14))
    hint = tk.Label(footer, text=f"{seconds} 秒后自动关闭",
                    font=("Microsoft YaHei UI", 8), bg=bg, fg="#9CA3AF")
    hint.pack(side="left")
    tk.Button(footer, text="知道了", command=root.destroy, relief="flat", bd=0,
              bg="#EFF6FF", fg="#2563EB", activebackground="#DBEAFE",
              font=("Microsoft YaHei UI", 9), padx=14, pady=3,
              cursor="hand2").pack(side="right")

    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = root.winfo_screenwidth() - w - 32
    y = root.winfo_screenheight() - h - 90
    root.geometry(f"{w}x{h}+{x}+{y}")

    remain = {"v": seconds}

    def tick() -> None:
        remain["v"] -= 1
        if remain["v"] <= 0:
            root.destroy()
        else:
            hint.config(text=f"{remain['v']} 秒后自动关闭")
            root.after(1000, tick)

    root.after(1000, tick)
    root.mainloop()


# ---------------------------------------------------------------- 自启动

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def has_tkinter(python_exe: str) -> bool:
    """探测某个解释器能不能用 tkinter（决定走自绘弹窗还是系统对话框）"""
    try:
        r = subprocess.run([python_exe, "-c", "import tkinter"], capture_output=True,
                           timeout=25, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def with_pythonw(exe: Path) -> Path:
    """换成同目录的 pythonw.exe，开机启动时不会闪黑框"""
    pythonw = exe.with_name("pythonw.exe")
    return pythonw if pythonw.exists() else exe


def candidate_interpreters() -> list[Path]:
    """候选解释器：当前这个 + py 启动器实际指向的那个"""
    out: list[Path] = []
    here = Path(sys.executable)
    for name in ("python.exe", "pythonw.exe"):
        p = here.with_name(name)
        if p.exists():
            out.append(p)

    try:
        r = subprocess.run(["py", "-3", "-c", "import sys; print(sys.executable)"],
                           capture_output=True, text=True, timeout=25,
                           creationflags=CREATE_NO_WINDOW)
        if r.returncode == 0 and r.stdout.strip():
            pointed = Path(r.stdout.strip())
            if pointed.exists():
                for name in ("python.exe", "pythonw.exe"):
                    p = pointed.with_name(name)
                    if p.exists():
                        out.append(p)
    except Exception:
        pass

    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def best_interpreter() -> Path:
    """挑一个带 tkinter 的解释器，并优先用 pythonw 版本"""
    for p in candidate_interpreters():
        if has_tkinter(str(p)):
            return with_pythonw(p)
    return with_pythonw(Path(sys.executable))


def launcher_command() -> str:
    """拼出注册表里要写的启动命令"""
    runner = best_interpreter()
    return f'"{runner}" "{Path(__file__).resolve()}" --run'


def relaunch_with_better_python(argv: list[str]) -> bool:
    """当前解释器没有 tkinter 时，换一个有的重新拉起自己"""
    if os.environ.get("BOOTSTAT_NO_REEXEC"):
        return False
    if has_tkinter(sys.executable):
        return False

    better = best_interpreter()
    if str(better).lower() == str(Path(sys.executable)).lower():
        return False

    try:
        subprocess.Popen([str(better), str(Path(__file__).resolve()), *argv],
                         creationflags=CREATE_NO_WINDOW,
                         env={**os.environ, "BOOTSTAT_NO_REEXEC": "1"})
        return True
    except Exception:
        return False


def install() -> int:
    import winreg

    cmd = launcher_command()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_RUN) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)

    runner = Path(cmd.split('"')[1])
    ui = "自绘弹窗（右下角，几秒自动消失）" if has_tkinter(str(runner)) \
        else "系统对话框（这个 Python 没装 tkinter，建议用 python.org 的正式版）"

    print("已写入开机自启（仅当前用户，无需管理员）：")
    print(f"  HKCU\\{REG_RUN}\\{APP_NAME}")
    print(f"  = {cmd}")
    print(f"界面模式：{ui}")
    print()
    print("下次登录 Windows 会自动运行。想立刻试一下：python bootstat.py --run")
    print("取消自启动：python bootstat.py --uninstall")
    return 0


def uninstall() -> int:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        print("已移除开机自启。")
    except FileNotFoundError:
        print("本来就没有安装自启动，无需操作。")
    return 0


# ---------------------------------------------------------------- 入口

def cmd_status() -> int:
    data = load_data()
    boots = data.get("boots", [])
    if not boots:
        print("还没有任何记录。运行 python bootstat.py --run 记录第一次。")
        return 0

    current = current_boot_at()
    print(f"数据文件：{data_file()}")
    print(f"累计记录：{len(boots)} 次　首次：{boots[0]['boot_at']}")
    print(f"本次开机：{current.strftime('%Y-%m-%d %H:%M:%S')}"
          f"（已运行 {human_duration(uptime_seconds())}）")
    print()
    print("最近 10 次：")
    for b in boots[-10:]:
        print(f"  {b['boot_at']}   启动耗时 {human_duration(b.get('startup_seconds', 0))}")
    return 0


def cmd_run(no_popup: bool) -> int:
    if not no_popup and relaunch_with_better_python(["--run"]):
        return 0  # 交给带 tkinter 的解释器去干活

    data = load_data()
    rec, is_new = record_boot(data)
    lines = build_summary(data, rec)

    if no_popup:
        print(("已记录" if is_new else "本次开机已记录过（去重）") + "：")
        for line in lines:
            print("  " + line)
        return 0

    show_popup(lines)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True, description="Windows 开机小助手")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--install", action="store_true", help="安装开机自启")
    group.add_argument("--uninstall", action="store_true", help="移除开机自启")
    group.add_argument("--status", action="store_true", help="查看统计")
    group.add_argument("--run", action="store_true", help="记录本次开机并弹窗（默认）")
    parser.add_argument("--no-popup", action="store_true", help="配合 --run，只记录不弹窗")
    args = parser.parse_args()

    if os.name != "nt":
        print("本程序只支持 Windows。")
        return 1

    if args.install:
        return install()
    if args.uninstall:
        return uninstall()
    if args.status:
        return cmd_status()
    return cmd_run(args.no_popup)


if __name__ == "__main__":
    sys.exit(main())
