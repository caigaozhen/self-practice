import platform
import tkinter
import winreg

from datetime import datetime
# 查看系统运行状态、进程信息
import psutil

CPU_REG_PATH = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
GB = 1024 ** 3


def timestamp_to_datetime(timestamp):
    """时间戳转为 ymdhss 格式"""
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')


def get_cpu_name():
    """查询电脑的cpu名称"""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CPU_REG_PATH) as key:
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except OSError:
        return "读取cpu名称失败"


def get_system_static_info() -> dict:
    """获取系统的静态数据"""

    drives = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        if usage.total == 0:
            continue
        drives.append((part.device, part.mountpoint, usage.total))

    return {
        "node": platform.node(),
        "system": f"{platform.system()} {platform.release()}",
        "version": platform.version(),
        "machine": platform.machine(),
        "boot_time": timestamp_to_datetime(psutil.boot_time()),
        "cpu_name": get_cpu_name(),
        "physical": psutil.cpu_count(logical=False) or 0,
        "logical": psutil.cpu_count(logical=True) or 0,
        "mem_total": psutil.virtual_memory().total,
        "freq": f"{psutil.cpu_freq().current:.0f} MHz",
        "drives": drives
    }


def get_system_info(si: dict) -> list[str]:
    """获取系统信息"""
    return [
        f"系统名称: {si['node']}",
        f"操作系统: {si['system']}",
        f"系统版本: {si['version']}",
        f"架构:{si['machine']}",
        f"开机时间: {si['boot_time']}"
    ]


def get_cpu_info(si: dict) -> list[str]:
    """获取cpu信息"""
    usage = psutil.cpu_percent(interval=None)
    return [
        f"CPU型号, {si['cpu_name']}",
        f"物理核心, {si['physical']}",
        f"逻辑核心, {si['logical']}",
        f"当前频率, {si['freq']}",
        f"CPU使用, {usage}",
    ]


def get_memory_info(si: dict) -> list[str]:
    """获取内存信息"""

    vm = psutil.virtual_memory()
    return [
        f"内存总数：: {si['mem_total'] / GB:.1f} GB",
        f"内存占用：: {vm.percent}%",
        f"内存可用：: {vm.available / GB:.1f} GB",
    ]


def get_disk_info(si: dict) -> list[str]:
    """获取硬盘信息"""

    lines = []
    for device, mountpoint, total in si["drives"]:
        try:
            usage = psutil.disk_usage(mountpoint)
        except (PermissionError, OSError):
            continue

        lines.append(
            f"{device:<2} 总{total / GB:.1f}GB"
            f"  可用 {usage.free / GB:.1f}GB"
            f"  已用 {usage.percent:.1f}%"
        )

    return lines or []


def build_text(si: dict) -> str:
    """四块文本：块内单换行，块间空一行。"""
    blocks = [get_system_info(si), get_cpu_info(si), get_memory_info(si), get_disk_info(si)]
    return "\n\n".join("\n".join(block) for block in blocks)


# 启动函数
if __name__ == "__main__":
    sinfo = get_system_static_info()

    root = tkinter.Tk()
    root.title("电脑硬件信息")
    root.geometry("640x500")

    label = tkinter.Label(
        root,
        text="正在采集…",
        justify="left",
        anchor="nw",
        font=("Consolas", 11),
    )
    label.pack(fill="both", expand=True, padx=12, pady=12)

    def refresh() -> None:
        label.config(text = build_text(sinfo))

    def tick() -> None:
        try:
            refresh()
        except (PermissionError, OSError):
            label.config(text = "刷新失败")
        finally:
            root.after(1200, tick)

    button = tkinter.Button(
        root,
        text="刷新",
        width=12,
        command=refresh,
    )
    button.pack(padx=12, pady=12)

    tick()
    root.mainloop()

