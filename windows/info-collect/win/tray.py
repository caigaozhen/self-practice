#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tray.py —— Windows 系统托盘图标（纯 ctypes，零依赖）

为什么不用 pystray：
    pystray 会连带引入 Pillow，为了一个托盘图标多两个第三方包，打包时
    每个包都是一个新的失败点。真正需要的只有 Shell_NotifyIconW 这一个 API。

它背后的机制其实很朴素：
    ① 注册一个窗口类 → ② 创建一个不可见的窗口 → ③ 告诉外壳"把图标挂在这个窗口上"
    ④ 用户点图标时，外壳给这个窗口发消息 → ⑤ 我们的 WNDPROC 收到后弹菜单

所以托盘不是"一个控件"，而是"一个窗口 + 一条注册记录"。窗口看不见，但它
必须有——外壳靠 hWnd 找到该把鼠标消息发给谁。

用法：
    tray = Tray(tooltip="...", menu=build_menu, on_command=dispatch)
    tray.run()          # 阻塞，直到 tray.stop() 或菜单里点"退出"

开发时可以直接跑本文件看效果（会显示一个演示托盘图标）：
    py -3 -X utf8 tray.py
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------- 常量

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_NULL = 0x0000
WM_APP = 0x8000

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10

MF_STRING, MF_SEPARATOR, MF_CHECKED, MF_GRAYED = 0x0000, 0x0800, 0x0008, 0x0001
TPM_LEFTALIGN, TPM_RETURNCMD, TPM_RIGHTBUTTON, TPM_NONOTIFY = 0x0000, 0x0100, 0x0002, 0x0080

IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x0010, 0x0040

IDI_APPLICATION = 32512

KS_LEFT, KS_RIGHT = 1, 2


# ---------------------------------------------------------------- 结构体

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

HMENU = wintypes.HANDLE
UINT_PTR = ctypes.c_size_t
HICON = wintypes.HANDLE


def _declare() -> None:
    """显式声明所有 API 的原型。

    这一步在 64 位 Windows 上是必须的，不是讲究：
    ctypes 默认把未声明的参数当 c_int（32 位），而 LPARAM 是 64 位。
    不声明的话，像 WM_GETMINMAXINFO 这类带指针 lParam 的消息会直接抛
    OverflowError，而且异常发生在回调里，只会打印一句 "Exception ignored"，
    界面看起来"只是有点怪"，非常难查。
    """
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]

    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]

    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
    ]

    user32.GetMessageW.restype = ctypes.c_int
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]

    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]

    user32.CreatePopupMenu.restype = HMENU
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.AppendMenuW.argtypes = [HMENU, wintypes.UINT, UINT_PTR, wintypes.LPCWSTR]
    user32.TrackPopupMenu.restype = ctypes.c_uint
    user32.TrackPopupMenu.argtypes = [HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    user32.DestroyMenu.argtypes = [HMENU]

    user32.SetTimer.restype = UINT_PTR
    user32.SetTimer.argtypes = [wintypes.HWND, UINT_PTR, wintypes.UINT, ctypes.c_void_p]
    user32.KillTimer.argtypes = [wintypes.HWND, UINT_PTR]

    user32.LoadImageW.restype = HICON
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadIconW.restype = HICON
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]

    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                          ctypes.POINTER(NOTIFYICONDATAW)]

    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    """Vista 之后的完整版。szTip 最长 128 个宽字符，超了会被截断。"""
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


_declare()      # 结构体都定义好了，这时才能落地原型


# ---------------------------------------------------------------- 菜单项描述

class Item:
    """一条菜单项。label 可以是空串（分隔线），checked 为 None 表示不带勾。"""

    __slots__ = ("label", "action", "checked", "enabled", "sep")

    def __init__(self, label="", action=None, checked=None, enabled=True, sep=False):
        self.label = label
        self.action = action
        self.checked = checked
        self.enabled = enabled
        self.sep = sep


def sep(label: str = "-") -> Item:
    return Item(label=label, sep=True)


# ---------------------------------------------------------------- 托盘

class Tray:
    """一个托盘图标 + 一个消息循环。

    menu: 回调，返回 list[Item]。每次右键都会重新调用一次，所以标签可以
          写成动态的（例如"今日 1 小时 23 分"）。
    """

    CLASS_NAME = "InfoCollectTrayWnd"
    WM_TRAYICON = WM_APP + 1
    TIMER_TIP = 1

    def __init__(self, tooltip: str = "InfoCollect", menu=None, icon_path: Path | None = None,
                 log=None, on_timer=None, on_endsession=None, on_start=None) -> None:
        self.tooltip = tooltip[:127]
        self.menu_builder = menu
        self.icon_path = Path(icon_path) if icon_path else None
        self.log = log
        self.on_timer = on_timer      # 定时器回调；为 None 时只刷新 tooltip
        self.on_endsession = on_endsession   # 关机/注销时收尾（GUI 程序的唯一机会）
        self.on_start = on_start      # 图标挂上之后回调一次（此时才能弹通知）

        self.hwnd = None
        self.hicon = None
        self._nid = None
        self._wndproc = None          # 必须保住引用：GC 掉的话消息一来就崩
        self._running = False
        self._timer_ms = 0

    # ------------------------------------------------------------ 内部

    def _err(self, what: str) -> None:
        code = ctypes.get_last_error()
        if self.log:
            self.log.warning("%s 失败，GetLastError=%s", what, code)

    def _load_icon(self):
        if self.icon_path and self.icon_path.exists():
            h = user32.LoadImageW(None, str(self.icon_path), IMAGE_ICON, 0, 0,
                                  LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                return h
        h = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
        return h

    def _build_nid(self, flags: int) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = self.WM_TRAYICON
        nid.hIcon = self.hicon
        nid.szTip = self.tooltip
        return nid

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == self.WM_TRAYICON:
                # 老式回调约定：lParam 的低位是鼠标消息
                mouse = lparam & 0xFFFF
                if mouse in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._popup_menu()
                    return 0
                if mouse == WM_LBUTTONDBLCLK:
                    self._invoke_default()
                    return 0
                if mouse == WM_LBUTTONUP:
                    # 单击刷新提示（很多人习惯点一下看数字）
                    self.refresh_tooltip()
                    return 0
            elif msg == WM_TIMER:
                if wparam == self.TIMER_TIP:
                    if self.on_timer is not None:
                        try:
                            self.on_timer()
                        except Exception:
                            if self.log:
                                self.log.exception("托盘定时回调异常")
                    else:
                        self.refresh_tooltip()
                return 0
            elif msg == WM_QUERYENDSESSION:
                # 关机/注销前系统最后问一句"可以关吗"。这里必须**同步做完**
                # 收尾工作再返回，因为返回值一给出，系统很快就会终止我们。
                # 无控制台的进程（pythonw / windowed exe）收不到
                # SetConsoleCtrlHandler 的回调，这里是唯一的机会。
                if self.on_endsession:
                    try:
                        self.on_endsession("query")
                    except Exception:
                        if self.log:
                            self.log.exception("关机收尾异常")
                return 1                     # TRUE = 不阻止关机
            elif msg == WM_ENDSESSION:
                if wparam and self.on_endsession:
                    try:
                        self.on_endsession("end")
                    except Exception:
                        if self.log:
                            self.log.exception("会话结束收尾异常")
                return 0
            elif msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            elif msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            if self.log:
                self.log.exception("托盘消息处理异常 msg=%s", msg)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _popup_menu(self) -> None:
        items = []
        if self.menu_builder:
            try:
                items = list(self.menu_builder() or [])
            except Exception:
                if self.log:
                    self.log.exception("构建托盘菜单失败")
                items = []

        hmenu = user32.CreatePopupMenu()
        if not hmenu:
            self._err("CreatePopupMenu")
            return
        try:
            ids: dict[int, Item] = {}
            for i, it in enumerate(items, start=1):
                if it.sep or not it.label:
                    user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                    continue
                flags = MF_STRING
                if it.checked is not None:
                    flags |= MF_CHECKED if it.checked else 0
                if not it.enabled or it.action is None:
                    flags |= MF_GRAYED
                user32.AppendMenuW(hmenu, flags, i, it.label)
                ids[i] = it

            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            # SetForegroundWindow 是必须的：否则菜单弹出后点别处不会消失
            user32.SetForegroundWindow(self.hwnd)
            cmd = user32.TrackPopupMenu(
                hmenu,
                TPM_LEFTALIGN | TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                pt.x, pt.y, 0, self.hwnd, None,
            )
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)   # 另一个已知的菜单残留 bug
        finally:
            user32.DestroyMenu(hmenu)

        chosen = ids.get(cmd)
        if chosen and chosen.action:
            try:
                chosen.action()
            except Exception:
                if self.log:
                    self.log.exception("托盘菜单动作异常")

    def _invoke_default(self) -> None:
        if not self.menu_builder:
            return
        try:
            for it in self.menu_builder() or []:
                if not it.sep and it.label and it.action:
                    it.action()
                    return
        except Exception:
            if self.log:
                self.log.exception("双击默认动作异常")

    # ------------------------------------------------------------ 对外

    def refresh_tooltip(self, text: str | None = None) -> None:
        if text is not None:
            self.tooltip = text[:127]
        if not self._nid:
            return
        nid = self._build_nid(NIF_TIP)
        if not shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)):
            self._err("Shell_NotifyIcon(MODIFY)")

    def notify(self, title: str, text: str, info_flags: int = 0x01) -> None:
        """弹出气泡提示（Win10+ 会变成右下角通知）。只在真的需要提醒时用。"""
        if not self._nid:
            return
        nid = self._build_nid(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = info_flags
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def set_timer(self, ms: int) -> None:
        """每隔 ms 毫秒自动刷新一次 tooltip。传 0 关闭。"""
        self._timer_ms = ms
        if self.hwnd:
            if ms:
                user32.SetTimer(self.hwnd, self.TIMER_TIP, ms, None)
            else:
                user32.KillTimer(self.hwnd, self.TIMER_TIP)

    def stop(self) -> None:
        self._running = False
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # ------------------------------------------------------------ 消息循环

    def run(self) -> int:
        hinst = kernel32.GetModuleHandleW(None)

        self._wndproc = WNDPROC(self._wnd_proc)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = self.CLASS_NAME
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:                    # 1410 = 类已注册，忽略
                self._err("RegisterClassExW")
                return 1

        # 一个不可见的普通窗口。样式给 0 就不会显示出来。
        self.hwnd = user32.CreateWindowExW(
            0, self.CLASS_NAME, "InfoCollect", 0, 0, 0, 0, 0, None, None, hinst, None
        )
        if not self.hwnd:
            self._err("CreateWindowExW")
            return 1

        self.hicon = self._load_icon()
        self._nid = self._build_nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid)):
            self._err("Shell_NotifyIcon(ADD)")
            self._nid = None
            return 1

        if self.on_start:
            try:
                self.on_start()
            except Exception:
                if self.log:
                    self.log.exception("托盘启动回调异常")

        if self._timer_ms:
            self.set_timer(self._timer_ms)

        self._running = True
        msg = wintypes.MSG()
        try:
            while self._running:
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:          # 0 = WM_QUIT，-1 = 出错
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            # 不删的话，进程退出后图标会一直挂在那儿，直到鼠标划过才消失
            if self._nid:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
                self._nid = None
            if self.hwnd:
                user32.DestroyWindow(self.hwnd)
                self.hwnd = None
        return 0


# ---------------------------------------------------------------- 演示

def _demo() -> int:
    here = Path(__file__).resolve().parent
    ico = here / "infocollect.ico"
    if not ico.exists():
        try:
            import icon as icon_mod
            icon_mod.ensure_icon(ico)
        except Exception:
            ico = None

    clicks = {"n": 0}

    def menu():
        return [
            Item(f"演示计数：{clicks['n']} 次", None),
            sep(),
            Item("点我 +1", lambda: clicks.__setitem__("n", clicks["n"] + 1)),
            Item("刷新提示", lambda: t.refresh_tooltip(f"演示 {clicks['n']} 次")),
            sep(),
            Item("退出", lambda: t.stop()),
        ]

    t = Tray(tooltip="InfoCollect 演示 —— 右键看菜单", menu=menu, icon_path=ico)
    t.set_timer(5000)
    print("托盘已启动，右键点图标看菜单。10 秒后自动退出。")
    if hasattr(sys, "_demo_timer"):
        pass
    import threading
    threading.Timer(10, t.stop).start()
    return t.run()


if __name__ == "__main__":
    if sys.stdout:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(_demo())
