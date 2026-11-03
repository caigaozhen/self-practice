#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
winapi.py —— Windows 采集接口封装

设计原则：
  1. 只依赖标准库（ctypes），不引入任何第三方包
  2. **所有函数都不抛异常**——采集失败一律返回兜底值，绝不因为
     拿不到某个数据就让整个采集进程崩掉
  3. 模块内不 print，不写日志，纯数据获取（方便单测）

单独运行可以实时观察采集效果：
    py -3 -X utf8 winapi.py          # 每秒打印一次，Ctrl+C 结束
    py -3 -X utf8 winapi.py 10       # 打印 10 次
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

# ---------------------------------------------------------------- 常量

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DESKTOP_READOBJECTS = 0x0001
DESKTOP_SWITCHDESKTOP = 0x0100

# UWP / 商店应用的宿主进程：它们的前台窗口永远属于它，真实应用在子窗口里
FRAME_HOST = "applicationframehost.exe"

# ---------------------------------------------------------------- DLL 与签名

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


# 返回值类型必须显式声明，否则 64 位返回值会被截成 32 位有符号整数
kernel32.GetTickCount64.restype = ctypes.c_ulonglong

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenInputDesktop.restype = wintypes.HANDLE
user32.CloseDesktop.argtypes = [wintypes.HANDLE]

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


# ---------------------------------------------------------------- 数据结构

@dataclass(frozen=True)
class Foreground:
    """前台窗口快照。取不到的部分是空串，不是 None——调用方少判空。"""
    app: str = "unknown.exe"   # 进程名，小写，含扩展名
    title: str = ""            # 窗口标题（可能为空，属于正常情况）
    cls: str = ""              # 窗口类名
    pid: int = 0
    hwnd: int = 0
    ok: bool = False           # False 表示这次采集失败（比如锁屏、无前台窗口）


# ---------------------------------------------------------------- 基础能力

def get_idle_seconds() -> float:
    """距上次键鼠输入过了多少秒。取不到时返回 0.0（当作"刚有输入"）。"""
    try:
        lii = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        now = kernel32.GetTickCount64()
        # dwTime 是 32 位 tick，49.7 天回绕；用掩码处理，避免算出负数
        diff = (now - lii.dwTime) & 0xFFFFFFFF
        return diff / 1000.0
    except Exception:
        return 0.0


def is_locked() -> bool:
    """当前工作站是否已锁屏。

    原理：锁屏时拿不到"输入桌面"的句柄。这是常见做法，但本机未实测锁屏态，
    失败时返回 False（宁可当作"没锁"，也不误判成锁屏导致停止采集）。
    """
    try:
        h = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS | DESKTOP_SWITCHDESKTOP)
        if not h:
            return True
        user32.CloseDesktop(h)
        return False
    except Exception:
        return False


def _process_name(pid: int) -> str:
    """PID → 可执行文件名（小写）。失败返回空串。"""
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""          # 权限不足（前台是提权程序）时会走到这里
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def _child_pids(hwnd: int, limit: int = 64) -> list[int]:
    """枚举窗口的所有子窗口 PID。用于穿透 ApplicationFrameHost。"""
    pids: list[int] = []

    def _cb(child, _lparam):
        try:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(child, ctypes.byref(pid))
            if pid.value:
                pids.append(pid.value)
        except Exception:
            pass
        return len(pids) < limit      # 返回 False 就停止枚举

    try:
        user32.EnumChildWindows(hwnd, WNDENUMPROC(_cb), 0)
    except Exception:
        pass
    return pids


def _real_app_for_host(hwnd: int) -> str:
    """前台是 ApplicationFrameHost 时，从子窗口里找出真实应用的进程名。"""
    for pid in _child_pids(hwnd):
        name = _process_name(pid)
        if name and name != FRAME_HOST:
            return name
    return ""


# ---------------------------------------------------------------- 主接口

def get_foreground() -> Foreground:
    """取当前前台窗口的进程名、标题、类名。任何一步失败都不抛异常。"""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return Foreground()

        # 标题（长度 + 1 给结尾的 \0，否则中文会被截断最后一个字符）
        n = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value

        # 类名
        cbuf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cbuf, 256)
        cls = cbuf.value

        # 进程
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        app = _process_name(pid.value)

        # 穿透 UWP 宿主进程
        if app == FRAME_HOST:
            real = _real_app_for_host(hwnd)
            if real:
                app = real

        return Foreground(
            app=app or "unknown.exe",
            title=title,
            cls=cls,
            pid=pid.value,
            hwnd=hwnd,
            ok=True,
        )
    except Exception:
        return Foreground()


# ---------------------------------------------------------------- 自测入口

def _probe(times: int = 0) -> None:
    """实时打印采集结果。times=0 表示一直跑。"""
    import sys
    import time

    # 让中文标题能在控制台正常显示（注意：必须在任何输出之前做）
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("idle秒  app                    class                 title")
    print("-" * 100)
    i = 0
    try:
        while times == 0 or i < times:
            fg = get_foreground()
            print(
                f"{get_idle_seconds():>6.1f}  {fg.app:<22} {fg.cls:<21} "
                f"{fg.title[:50]}"
                + ("" if fg.ok else "   [采集失败]"),
                flush=True,
            )
            i += 1
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else "0"
    try:
        _probe(int(arg))
    except ValueError:
        _probe(0)
