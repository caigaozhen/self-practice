#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
autostart.py —— 开机自启（写 HKCU\\...\\Run，不用管理员）

这个模块只解决一个问题：**开机后用什么命令把本程序拉起来**。

两种运行形态，写出来的命令完全不同，混了就会静默失效：

    源码形态：  "C:\\...\\pythonw.exe" "F:\\...\\app.py" tray
    打包形态：  "C:\\...\\InfoCollect.exe" tray

判断依据是 sys.frozen（PyInstaller 会把它设成 True）。
不过默认策略是**有 exe 就用 exe**（见 packaged_exe）：源码形态自启把某个
pythonw.exe 的绝对路径钉死，Python 一升级/卸载就静默失效，很难发现。
源码形态下还必须挑一个**带 tkinter 的解释器**，否则配置界面打不开——
这一点是从 bootstat 项目踩出来的坑：当时默认的 WorkBuddy 内置 Python
没有 tkinter，弹窗直接退化成丑陋的系统对话框。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "InfoCollect"
REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = APP_NAME

# 启动参数：tray = 无窗口常驻，只显示托盘图标
LAUNCH_ARGS = "tray"


# ---------------------------------------------------------------- 运行形态

def is_frozen() -> bool:
    """是不是被 PyInstaller 打包过。"""
    return bool(getattr(sys, "frozen", False))


def program_dir() -> Path:
    """程序所在目录。

    打包后 __file__ 指向临时解压目录（onefile 模式下每次启动都不一样），
    必须用 sys.executable 才稳。这四个字是整个打包环节最容易翻车的地方。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def entry_script() -> Path:
    return program_dir() / "app.py"


def packaged_exe() -> Path | None:
    """找打包好的 exe；找不到返回 None。

    为什么自启要优先用 exe（哪怕当前是源码形态）：
      源码形态的自启命令钉死了某个 pythonw.exe 的绝对路径，一旦那个 Python 被
      升级、卸载、或者 venv 被删，开机就静默不启动——而且很难发现，因为
      没有任何报错。exe 自带解释器，跟本机 Python 环境彻底解耦。

    两个候选位置：
      win/InfoCollect.exe                   有人把 exe 拷到源码目录旁边
      win/dist/InfoCollect/InfoCollect.exe   PyInstaller 的标准输出位置
    """
    if is_frozen():
        return Path(sys.executable).resolve()
    for p in (program_dir() / "InfoCollect.exe",
              program_dir() / "dist" / APP_NAME / "InfoCollect.exe"):
        if p.is_file():
            return p.resolve()
    return None


# ---------------------------------------------------------------- 解释器挑选

def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def has_tkinter(python: str) -> bool:
    """探测某个解释器能不能 import tkinter。

    必须用子进程问，不能在当前进程 import——因为当前进程可能就是缺 tkinter 的那个。
    """
    if not python or not Path(python).exists():
        return False
    try:
        r = subprocess.run(
            [python, "-c", "import tkinter"],
            capture_output=True,
            timeout=10,
            creationflags=_no_window_flags(),
        )
        return r.returncode == 0
    except Exception:
        return False


def _with_pythonw(exe: str) -> str:
    """把 python.exe 换成同目录的 pythonw.exe（GUI 子系统，启动不闪黑框）。"""
    p = Path(exe)
    w = p.with_name("pythonw.exe")
    return str(w) if w.exists() else str(p)


def candidate_interpreters() -> list[str]:
    out: list[str] = [sys.executable]

    # py 启动器指向的那个
    try:
        r = subprocess.run(
            ["py", "-3", "-c", "import sys; print(sys.executable)"],
            capture_output=True, text=True, timeout=10,
            creationflags=_no_window_flags(),
        )
        if r.returncode == 0 and r.stdout.strip():
            out.append(r.stdout.strip())
    except Exception:
        pass

    # 常见的按用户安装路径
    local = os.environ.get("LOCALAPPDATA")
    if local:
        base = Path(local) / "Programs" / "Python"
        if base.is_dir():
            out.extend(str(p) for p in sorted(base.glob("Python3*/python.exe"), reverse=True))

    seen, uniq = set(), []
    for p in out:
        if not p:
            continue
        key = os.path.normcase(os.path.abspath(p))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def pick_interpreter() -> tuple[str, bool]:
    """挑一个能跑配置界面的解释器。

    返回 (解释器路径, 是否带 tkinter)。都带不上 tkinter 时退而求其次，
    用当前解释器——采集照常，只是配置窗打不开。
    """
    for exe in candidate_interpreters():
        if has_tkinter(exe):
            return _with_pythonw(exe), True
    return _with_pythonw(sys.executable), False


# ---------------------------------------------------------------- 命令行

def launcher_command(mode: str = "auto") -> str:
    """拼出要写进注册表的那一整串命令。

    mode：
        auto    有打包好的 exe 就用它，没有才退回 pythonw + app.py（默认）
        exe     必须是 exe，找不到就抛 FileNotFoundError 让调用方提示
        python  强制源码形态，改代码调试时用

    注意两段路径都必须加引号：Windows 把这条字符串原样交给 CreateProcess，
    路径里带空格不加引号，会被按空格切成多个参数（老牌提权漏洞的成因）。
    """
    if mode not in ("auto", "exe", "python"):
        raise ValueError(f"未知 mode：{mode}")

    if mode != "python":
        exe = packaged_exe()
        if exe is not None:
            return f'"{exe}" {LAUNCH_ARGS}'
        if mode == "exe":
            raise FileNotFoundError("没找到 InfoCollect.exe，先打包一次（build_exe.bat）")

    python, _ = pick_interpreter()
    script = entry_script().resolve()
    return f'"{python}" "{script}" {LAUNCH_ARGS}'


# ---------------------------------------------------------------- 注册表

def current_value() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN) as key:
            val, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return str(val)
    except FileNotFoundError:
        return None
    except OSError:
        return None


def is_enabled() -> bool:
    return current_value() is not None


def install(mode: str = "auto") -> tuple[bool, str]:
    """写入自启。返回 (成功?, 给用户看的说明)。"""
    import winreg

    try:
        cmd = launcher_command(mode)
    except Exception as e:
        # 找不到 exe 之类的问题在这里就该说清楚，别写成"注册表失败"
        return False, str(e)

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_RUN) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, cmd)
        return True, cmd
    except Exception as e:
        return False, f"写入注册表失败：{type(e).__name__}: {e}"


def uninstall() -> tuple[bool, str]:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True, "已移除"
    except FileNotFoundError:
        return True, "本来就没装"
    except Exception as e:
        return False, f"删除失败：{type(e).__name__}: {e}"


def set_enabled(on: bool, mode: str = "auto") -> tuple[bool, str]:
    return install(mode) if on else uninstall()


# ---------------------------------------------------------------- 自检

def diagnose() -> dict:
    """状态页 / 配置界面用。返回一套可读的诊断信息。"""
    val = current_value()
    exe = packaged_exe()
    info = {
        "enabled": val is not None,
        "command": val or "",
        "frozen": is_frozen(),
        "expected": launcher_command(),
        "exe": str(exe) if exe else "",
        "stale": False,          # 注册表指着一个已经不存在的位置
        "missing_tk": False,
    }
    if val:
        # 粗略检查：命令里的路径还在不在
        parts = [p for p in val.replace('"', "|").split("|") if p.strip().lower().endswith((".exe", ".py"))]
        info["stale"] = any(not Path(p.strip()).exists() for p in parts)
    elif not is_frozen():
        _, ok = pick_interpreter()
        info["missing_tk"] = not ok
    return info


if __name__ == "__main__":
    import json

    sys.stdout.reconfigure(encoding="utf-8") if sys.stdout else None
    d = diagnose()
    print(f"运行形态：{'打包 exe' if d['frozen'] else '源码 + 解释器'}")
    print(f"应写命令：{d['expected']}")
    print(f"当前状态：{'已启用' if d['enabled'] else '未启用'}")
    if d["enabled"]:
        print(f"注册表值：{d['command']}")
        if d["stale"]:
            print("⚠ 警告：命令里的某个路径已经不存在了，自启会静默失败")
        elif d["command"] != d["expected"]:
            print("⚠ 提示：注册表指向的路径与当前程序位置不同（可能移动过目录）")
    print()
    print("path_exists:", {k: str(v) for k, v in {"app.py": entry_script()}.items()},
          entry_script().exists())
