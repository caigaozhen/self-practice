"""V0.3：采集电脑硬件数据，并每秒自动刷新。

相比 V0.2，改了三件事：
    1. 静态信息（计算机名、CPU 型号、内存总量…）只在启动时采一次
    2. 动态信息（CPU 使用率、内存可用、磁盘已用…）每秒更新一次
    3. cpu_percent 改成非阻塞模式，第一次的返回值必须丢弃

界面结构、打包方式都和 V0.2 一样。
"""

import platform
import sys
import time
import tkinter as tk
import winreg

import psutil

CPU_REG_PATH = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
GB = 1024**3
REFRESH_MS = 1000  # 刷新间隔（毫秒）


# ------------------------------------------------------------------ 静态信息
# 「静态」= 程序运行期间基本不会变的值。采一次存进字典，反复使用。


def read_cpu_name() -> str:
    """从注册表读 CPU 型号；读不到就返回固定文案，不让整页崩掉。"""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CPU_REG_PATH) as key:
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except OSError:
        return "读取失败"


def collect_static() -> dict:
    """启动时只调用一次，把不变的项一次性收进字典。"""
    drives = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue  # 空光驱、没插卡的读卡器会打不开
        if usage.total == 0:
            continue
        drives.append((part.device, part.mountpoint, usage.total))  # 盘符 / 挂载点 / 总容量

    freq = psutil.cpu_freq()
    return {
        "node": platform.node(),
        "system": f"{platform.system()} {platform.release()}",
        "version": platform.version(),
        "machine": platform.machine(),
        "cpu_name": read_cpu_name(),
        "physical": psutil.cpu_count(logical=False) or 0,
        "logical": psutil.cpu_count(logical=True) or 0,
        # Windows 上 cpu_freq 读的是注册表里的标称频率，运行期间不会变，所以归静态
        "freq": f"{freq.current:.0f} MHz" if freq else "读取失败",
        "mem_total": psutil.virtual_memory().total,
        "boot": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(psutil.boot_time())),
        "drives": drives,
    }


# ------------------------------------------------------------------ 文本块
# 每个函数返回「若干行字符串」，块与块怎么拼交给 build_text()。


def system_block(st: dict) -> list[str]:
    """系统信息块。"""
    return [
        f"计算机   : {st['node']}",
        f"操作系统 : {st['system']}",
        f"系统版本 : {st['version']}",
        f"架构     : {st['machine']}",
        f"开机时间 : {st['boot']}",
    ]


def cpu_block(st: dict) -> list[str]:
    """CPU 信息块。"""
    # interval=None：立刻返回「距上次调用以来」的平均值，不卡界面。"""
    usage = psutil.cpu_percent(interval=None)
    return [
        f"CPU 型号 : {st['cpu_name']}",
        f"核心数量 : {st['physical']} 物理 / {st['logical']} 逻辑",
        f"当前频率 : {st['freq']}",
        f"CPU 使用 : {usage}%",
    ]


def memory_block(st: dict) -> list[str]:
    """内存信息块。"""
    vm = psutil.virtual_memory()
    return [
        f"内存总量 : {st['mem_total'] / GB:.1f} GB",
        f"内存可用 : {vm.available / GB:.1f} GB",
        f"内存占用 : {vm.percent}%",
    ]


def disk_block(st: dict) -> list[str]:
    """磁盘信息块。"""
    lines = []
    for device, mountpoint, total in st["drives"]:
        try:
            usage = psutil.disk_usage(mountpoint)
        except (PermissionError, OSError):
            continue  # 采样期间盘被拔了也不崩
        lines.append(
            f"{device:<4} 总 {total / GB:7.1f} GB"
            f"   可用 {usage.free / GB:7.1f} GB"
            f"   已用 {usage.percent:5.1f}%"
        )
    return lines or ["磁盘     : 读取失败"]


def build_text(st: dict) -> str:
    """四块文本：块内单换行，块间空一行。"""
    blocks = [system_block(st), cpu_block(st), memory_block(st), disk_block(st)]
    return "\n\n".join("\n".join(block) for block in blocks)


# ------------------------------------------------------------------ 界面

if __name__ == "__main__":
    # 预热：第一次调用只建立基准，返回值一定是 0.0，直接丢弃
    psutil.cpu_percent(interval=None)

    static = collect_static()  # 静态信息只采这一次

    root = tk.Tk()
    root.title("电脑硬件信息")
    root.geometry("640x500")

    label = tk.Label(
        root,
        text="正在采集…",
        justify="left",
        anchor="nw",
        font=("Consolas", 11),
    )
    label.pack(fill="both", expand=True, padx=12, pady=12)

    def refresh() -> None:
        """采一次动态信息并刷新到标签上。"""
        label.config(text=build_text(static))

    def tick() -> None:
        """每秒触发一次：先刷新，再排下一次。"""
        try:
            refresh()
        except Exception as exc:  # 采集出错也只显示提示，不让循环断掉
            label.config(text=f"刷新失败：{exc}")
        finally:
            # after 在 REFRESH_MS 时间后，在调用一次 tick()
            root.after(REFRESH_MS, tick)  # 无论成败都排下一次，循环才不会停

    # 按钮只调 refresh，不排 after —— 点多少次都只有一条定时链
    button = tk.Button(root, text="刷新", width=12, command=refresh)
    button.pack(pady=(0, 12))

    tick()  # 立刻刷新一次，同时启动每秒循环

    if "--selftest" in sys.argv:
        root.after(1200, root.destroy)  # 自动关闭，用于验证 exe 能正常启动

    root.mainloop()
