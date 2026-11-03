#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shutdown.py —— 捕获 Windows 的关机 / 注销 / 关闭控制台事件

原理：控制台程序可以注册 SetConsoleCtrlHandler，系统在关机时会调用它
（CTRL_SHUTDOWN_EVENT），给程序一个"临死前做点事"的机会。

重要限制：
  * 只在**有控制台**的进程里有效。用 pythonw.exe 或打包成 --noconsole 的 exe
    运行时没有控制台，这个回调不会被调用，需要改成隐藏窗口 + WM_QUERYENDSESSION。
  * 系统只给 3~5 秒（Console 程序的默认等待时间），超时直接 terminate。
    所以回调里只能做"短平快"的事：结算会话 + 一次短超时推送。

因此本项目不依赖它来保证数据完整，真正兜底的是 uploaded 标记 + 下次启动补传。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

CTRL_C_EVENT = 0
CTRL_BREAK_EVENT = 1
CTRL_CLOSE_EVENT = 2
CTRL_LOGOFF_EVENT = 5
CTRL_SHUTDOWN_EVENT = 6

EVENT_NAMES = {
    CTRL_C_EVENT: "Ctrl+C",
    CTRL_BREAK_EVENT: "Ctrl+Break",
    CTRL_CLOSE_EVENT: "关闭控制台窗口",
    CTRL_LOGOFF_EVENT: "用户注销",
    CTRL_SHUTDOWN_EVENT: "系统关机",
}

HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.SetConsoleCtrlHandler.argtypes = [HANDLER, wintypes.BOOL]
_kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL

# 回调对象必须常驻，否则会被 GC 回收，系统回调时野指针崩溃
_keepalive: list = []


def install(callback) -> bool:
    """注册退出回调。callback(reason:int) 会在系统创建的独立线程里被调用。

    返回 False 表示注册失败（通常是进程没有控制台）。
    """
    def _handler(event: int) -> bool:
        if event in (CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
            try:
                callback(event)
            except Exception:
                pass
            return True
        return False

    try:
        routine = HANDLER(_handler)
        ok = bool(_kernel32.SetConsoleCtrlHandler(routine, True))
        if ok:
            _keepalive.append(routine)
        return ok
    except Exception:
        return False
