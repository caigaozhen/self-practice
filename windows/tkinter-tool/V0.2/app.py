"""V0.2：采集电脑硬件数据，显示在窗口里。

相比 V0.1，加了两件事：
    1. 数据不再写死，改成每次运行时现场采集
    2. 加一个「刷新」按钮，点一下重新采一次

数据来源分两条路：
    platform / winreg  —— 标准库，取系统版本、CPU 型号
    psutil             —— 第三方库，取核心数、频率、使用率、内存、磁盘

界面结构、打包方式都和 V0.1 一样。
"""

import platform
import sys
import time
import tkinter as tk
import winreg

import psutil

CPU_REG_PATH = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
GB = 1024**3


# ------------------------------------------------------------------ 采集：系统


def get_system_info() -> list[str]:
    """计算机名、系统版本、架构、开机时间。"""
    boot = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(psutil.boot_time()))
    return [
        f"计算机   : {platform.node()}",
        f"操作系统 : {platform.system()} {platform.release()}",
        f"系统版本 : {platform.version()}",
        f"架构     : {platform.machine()}",
        f"开机时间 : {boot}",
    ]


# ------------------------------------------------------------------ 采集：CPU


def get_cpu_info() -> list[str]:
    """CPU 型号读注册表，其余指标由 psutil 提供。"""
    name = "读取失败"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CPU_REG_PATH) as key:
            name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except OSError:
        pass  # 读不到就显示「读取失败」，不让整页崩掉

    # 核心数：物理核心数 / 逻辑核心数
    physical = psutil.cpu_count(logical=False) or 0
    logical = psutil.cpu_count(logical=True) or 0

    freq = psutil.cpu_freq()
    freq_text = f"{freq.current:.0f} MHz" if freq else "读取失败"

    usage = psutil.cpu_percent(interval=0.2)  # 采样 0.2 秒，界面会短暂停顿

    return [
        f"CPU 型号 : {name}",
        f"核心数量 : {physical} 物理 / {logical} 逻辑",
        f"当前频率 : {freq_text}",
        f"CPU 使用 : {usage}%",
    ]


# ------------------------------------------------------------------ 采集：内存


def get_memory_info() -> list[str]:
    """内存总量 / 可用 / 占用率。"""
    try:
        vm = psutil.virtual_memory()
    except Exception:
        return ["内存     : 读取失败"]

    return [
        f"内存总量 : {vm.total / GB:.1f} GB",
        f"内存可用 : {vm.available / GB:.1f} GB",
        f"内存占用 : {vm.percent}%",
    ]


# ------------------------------------------------------------------ 采集：磁盘


def get_disk_info() -> list[str]:
    """每个盘符的总容量、可用容量、已用比例。"""
    lines = []
    # all=False 只采集本地磁盘，不包括网络磁盘
    # all=True 采集所有磁盘，包括网络磁盘
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue  # 空光驱、未插入的读卡器会打不开，跳过
        if usage.total == 0:
            continue

        lines.append(
            # <4 表示左对齐，宽度为 4 字符
            # :7.1f 表示保留 1 位小数，宽度为 7 字符
            # :5.1f 表示保留 1 位小数，宽度为 5 字符
            f"{part.device:<4} 总 {usage.total / GB:7.1f} GB"
            f"   可用 {usage.free / GB:7.1f} GB"
            f"   已用 {usage.percent:5.1f}%"
        )

    return lines or ["磁盘     : 读取失败"]


# ------------------------------------------------------------------ 汇总


def collect_all() -> str:
    """把四块信息拼成一段文字，中间用空行隔开。"""
    blocks = [
        get_system_info(),
        get_cpu_info(),
        get_memory_info(),
        get_disk_info(),
    ]

    # 解释：\n\n 表示每个块之间用空行隔开 两次回车
    # 解释：\n 表示每个元素之间用换行隔开 一次回车
    return "\n\n".join("\n".join(block) for block in blocks)


# ------------------------------------------------------------------ 界面
# 注意：这段放在 if __name__ == "__main__" 里面。
# 好处是 import app 时只拿到采集函数，不会弹出窗口（方便单独测试）。

if __name__ == "__main__":
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
        """重新采集一遍并刷新到标签上。界面里不放写死的采集结果。"""
        # 此时代表修改label中的text内容
        label.config(text=collect_all())

    button = tk.Button(root, text="刷新", width=12, command=refresh)
    button.pack(pady=(0, 12))

    refresh()  # 打开窗口先采一次，不用等用户点按钮

    # 启动命令里面有 --selftest 参数，1200ms后自动关闭窗口
    if "--selftest" in sys.argv:
        root.after(1200, root.destroy)  # 自动关闭，用于验证 exe 能正常启动

    root.mainloop()
