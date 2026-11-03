#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_common.py —— 两个 tkinter 窗口共用的小工具

只做三件事：
    ① 打开 DPI 感知（不做的话，125% 缩放下整个界面是糊的）
    ② 窗口居中 / 约束最小尺寸
    ③ 一个统一的"当前进程是不是无控制台"判断
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from tkinter import ttk


def enable_dpi() -> None:
    """告诉 Windows"我自己处理缩放"。

    不调这个，系统会把窗口当位图拉伸（糊），而不是按逻辑像素重绘（清晰）。
    先试 Per-Monitor V2（Win10 1703+），失败再退到旧的 SetProcessDPIAware。
    """
    try:
        # -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def center(win: tk.Misc, width: int, height: int, min_w: int = 0, min_h: int = 0) -> None:
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2 - 20)
    win.geometry(f"{width}x{height}+{x}+{y}")
    if min_w or min_h:
        win.minsize(min_w or width, min_h or height)


def has_console() -> bool:
    """打包成 --windowed 的 exe 时没有控制台，print 无处可去。"""
    if sys.stdout is None:
        return False
    try:
        return bool(sys.stdout.isatty()) or sys.stderr is not None
    except Exception:
        return False


def bring_to_front(win: tk.Misc) -> None:
    """把窗口顶到最前并抢焦点。

    从托盘菜单拉起窗口时，Windows 不允许后台进程随便抢焦点，新窗口
    经常会开在别的窗口后面——用户以为"点了没反应"。先临时置顶 250ms
    再取消置顶，是最省事的绕法。

    ⚠ 必须先 update() 让窗口真正映射出来再置顶：对一个还没显示的窗口
    设置 -topmost，Windows 会把窗口放到默认的层叠位置上，之前算好的
    居中坐标就白算了（实测从 (620,170) 变成 (78,78)）。
    """
    try:
        win.update_idletasks()
        win.deiconify()
        win.update()                       # 真正 map 出来，位置才固定
        win.lift()
        win.attributes("-topmost", True)
        win.after(250, lambda: _unset_topmost(win))
        win.focus_force()
    except Exception:
        pass


def _unset_topmost(win: tk.Misc) -> None:
    """定时器可能比窗口活得久（用户秒关了窗口），这里必须吞掉异常。"""
    try:
        win.attributes("-topmost", False)
    except Exception:
        pass


def set_window_icon(win: tk.Misc) -> None:
    """给窗口换上自己的图标（否则标题栏是 Tk 那只羽毛）。"""
    try:
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "infocollect.ico")
        if os.path.exists(p):
            win.iconbitmap(default=p)
    except Exception:
        pass


def style(root: tk.Misc) -> ttk.Style:
    """统一一点观感：Windows 上用 vista 主题，字体给微软雅黑。"""
    st = ttk.Style(root)
    try:
        st.theme_use("vista")
    except Exception:
        pass
    for font_name in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"):
        try:
            import tkinter.font as tkfont
            if font_name in tkfont.families():
                st.configure(".", font=(font_name, 9))
                st.configure("Title.TLabel", font=(font_name, 12, "bold"))
                st.configure("Hint.TLabel", font=(font_name, 8), foreground="#666666")
                st.configure("Head.TLabel", font=(font_name, 9, "bold"))
                break
        except Exception:
            break
    return st
