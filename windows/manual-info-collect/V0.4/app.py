"""Windows 开机自启程序 · V0.4：单实例锁。"""

import ctypes
import os
import subprocess
import sys
import winreg
from pathlib import Path

from loguru import logger

# ------------------------------------------------------------------ 常量

REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ManualInfoCollect"

LOG_DIR = Path(os.environ["LOCALAPPDATA"]) / APP_NAME
LOG_FILE = LOG_DIR / "manual-info-collect.log"

MUTEX_NAME = rf"Local\{APP_NAME}_SingleInstance"
ERROR_ALREADY_EXISTS = 183

# 必须挂在模块级：句柄一丢，锁就没了
_mutex_handle = None

# ------------------------------------------------------------------ 日志

LOG_DIR.mkdir(parents=True, exist_ok=True)  # 目录不存在就新建

# 文件接收器：UTF-8、INFO 起记、10MB 轮转、保留 3 份
logger.add(
    LOG_FILE,
    encoding="utf-8",
    level="INFO",
    rotation="10 MB",
    retention=3,
    format="{time:YYYY-MM-DD HH:mm:ss} {level:<8} {message}",
)

# ------------------------------------------------------------------ 异常兜底


def handle_exception(exc_type, exc_value, exc_traceback):
    """兜住未捕获异常，把完整调用栈写进日志。

    exc_type      异常的类型（类），如 ZeroDivisionError
    exc_value     异常的实例，如 ZeroDivisionError('division by zero')
    exc_traceback 记录调用链的栈帧对象
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # 用户按 Ctrl+C 主动中断，交回默认处理，不记为错误
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.opt(exception=(exc_type, exc_value, exc_traceback)).error("未捕获异常，程序即将退出")


def install_excepthook():
    """把 handle_exception 挂到解释器的未捕获异常钩子上。"""
    sys.excepthook = handle_exception


# ------------------------------------------------------------------ 单实例锁


def acquire_single_instance() -> bool:
    """抢命名互斥体，返回 False 表示已经有一个实例在跑。

    没有这把锁：开机自启拉起一个 + 用户再双击一次 = 同一段时间记两遍。
    """
    global _mutex_handle

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]

    handle = kernel32.CreateMutexW(None, 0, MUTEX_NAME)
    if not handle:
        # 连互斥体都建不出来（权限异常等），宁可放行也别把程序卡死
        return True

    # 必须紧跟 CreateMutexW 读错误码，中间不要插入任何别的 API 调用
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return False

    _mutex_handle = handle
    return True


def alert(message: str) -> None:
    """没有控制台时 print 等于丢进虚空，只能用弹窗。"""
    if sys.stdout is not None:
        print(message)
        return
    ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x40)


# ------------------------------------------------------------------ 解释器探测


def has_tkinter(python_path: Path) -> bool:
    """用子进程试 import tkinter，返回是否成功。"""
    try:
        r = subprocess.run(
            [str(python_path), "-c", "import tkinter"],
            capture_output=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pick_python() -> Path:
    """优先选带 tkinter 的解释器，都不行就回退到当前解释器。"""
    candidates = [
        Path(sys.executable),
        Path(r"C:\Users\29242\AppData\Local\Programs\Python\Python314\python.exe"),
    ]

    for candidate in candidates:
        if candidate.exists() and has_tkinter(candidate):
            return candidate
    return Path(sys.executable)


# ------------------------------------------------------------------ 注册表


def command_paths(cmd: str) -> list[str]:
    """从启动命令里挑出 .exe 和 .py 路径，用于检查文件是否还在。"""
    paths = []
    for part in cmd.split('"'):
        s = part.strip()
        if s.endswith(".exe") or s.endswith(".py"):
            paths.append(s)
    return paths


def launcher_command() -> str:
    """拼出写进注册表的启动命令，用 pythonw 避免黑框。"""
    python = pick_python()
    exe = python.with_name("pythonw.exe")
    if not exe.exists():
        exe = python
    script = Path(__file__).resolve()
    return f'"{exe}" "{script}" --run'


def install() -> None:
    """写入 HKCU 的 Run 键，实现当前用户开机自启。"""
    cmd = launcher_command()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
    logger.info("安装自启项：{}", cmd)
    print("安装成功")


def uninstall() -> None:
    """删除 Run 键，原本不存在也算成功。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, APP_NAME)
        logger.info("已删除自启项：{}", APP_NAME)
        print("删除成功")
    except FileNotFoundError:
        logger.info("卸载时未找到自启项，视为已删除")
        print("本来就没有安装，无需删除")


def status() -> None:
    """检查自启项是否存在、路径是否有效、是否指向当前程序。"""
    expected = launcher_command()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN) as key:
            actual, _type = winreg.QueryValueEx(key, APP_NAME)
    except FileNotFoundError:
        actual = None

    print(f"当前状态：{'已安装' if actual else '未安装'}")

    if actual:
        missing = []
        for p in command_paths(actual):
            if not Path(p).exists():
                missing.append(p)

        if missing:
            print("当前启动命令中存在不存在的路径：")
            for p in missing:
                print(f"不存在的路径：{p}")

    if actual and actual != expected:
        print("⚠ 与当前程序位置不一致")
        print("预期启动命令：", expected)
        print("当前启动命令：", actual)

    python = pick_python()
    print(f"当前解释器：{python}")
    if has_tkinter(python):
        print("当前解释器已安装tkinter")
    else:
        print("当前解释器未安装tkinter")


# ------------------------------------------------------------------ 业务入口


def main() -> int:
    """开机自启后真正要干的活：先抢锁，抢到才干活。"""
    if not acquire_single_instance():
        logger.warning("已有实例在运行，本次启动放弃")
        alert(f"{APP_NAME} 已经在运行了。")
        return 1

    logger.info("程序开始运行了")
    return 0


if __name__ == "__main__":
    install_excepthook()

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "--install":
        install()
    elif cmd == "--uninstall":
        uninstall()
    elif cmd == "--status":
        status()
    else:
        # --run 或无参数：常驻入口，用退出码把结果告诉调用方
        sys.exit(main())
