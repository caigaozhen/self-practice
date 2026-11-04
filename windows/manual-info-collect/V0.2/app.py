from datetime import datetime
from pathlib import Path
import sys
import subprocess
import winreg

# 定义注册表路径和应用名称
REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ManualInfoCollect"

# 常量大写， 定义运行日志输出路径
LOG_FILE = Path(__file__).parent / "run.log"

#主函数
def main():
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}程序开始运行了" #f代表格式化字符串，:代表时间格式化
    with open(LOG_FILE, "a", encoding="utf-8") as file: # with语句自动关闭文件，无需手动关闭，open代表打开文件，a代表追加写入，encoding="utf-8"代表utf-8编码
        file.write(line + "\n")
    print(line)

#拼接启动命令
def launcher_command():
    python = pick_python() 
    # 这个地方使用pythonw.exe是为了隐藏窗口，不显示命令行窗口，其他跟python.exe没有区别
    exe = python.with_name("pythonw.exe") # 保留文件目录，只更换文件名
    if not exe.exists():
        exe = python
    script = Path(__file__).resolve() # 当前文件获取绝对路径
    return f'"{exe}" "{script}" --run'

# 写入用户注册表，实现开机自启
def install():
    cmd = launcher_command()
    # winreg是python自带的操作注册表的模块
    # HKEY_CURRENT_USER是当前用户的注册表根键
    # REG_RUN是注册表路径
    # 0是默认值
    # KEY_WRITE是写入权限
    # as key 代表将注册表键赋值给key变量
    # REG_SZ是字符串类型
    # APP_NAME是注册表键名
    # cmd是要填写的值
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        print("安装成功")

# 从注册表删除应用
def uninstall():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, APP_NAME)
            print("删除成功")
    except FileNotFoundError:
        print("本来就没有安装，无需删除")

# 检查启动命令中解释器路径，还有脚本路径
def command_paths(cmd: str) -> list[str]:
    paths = []
    for part in cmd.split('"'):
        s=part.strip()
        if s.endswith('.exe') or s.endswith('.py'):
            paths.append(s)
    return paths

# 检查应用是否安装
def status():
    expected = launcher_command()
    try:
        # 
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN) as key:
            actual, _type = winreg.QueryValueEx(key, APP_NAME)
    except FileNotFoundError:
        actual = None

    # 检查注册表中是否有key，有则说明已安装
    print(f"当前状态：{'已安装' if actual else '未安装'}")

    # 检查启动命令中是否存在不存在的路径
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

    # 检查当前解释器是否安装了tkinter
    python = pick_python()
    print(f"当前解释器：{python}")
    if has_tkinter(python):
        print("当前解释器已安装tkinter")
    else:
        print("当前解释器未安装tkinter")

    
# 检查是否安装tkinter
def has_tkinter(python_path: Path) -> bool:
    try:
        r = subprocess.run([str(python_path), "-c", "import tkinter"],   
                capture_output=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
                text=True)
        return r.returncode == 0

    except (OSError, subprocess.TimeoutExpired):
        return False

# 优先选择安装了tkinter的python解释器，否则返回默认解释器
def pick_python() -> Path:
    candidates = [
        # Path获取路径，sys.executable获取运行当前文件的脚本解释器的完整路径
        Path(sys.executable),
        Path(r"C:\Users\29242\AppData\Local\Programs\Python\Python314\python.exe"),
    ]

    for candidate in candidates:
        if candidate.exists() and has_tkinter(candidate):
            return candidate
    return Path(sys.executable)


if __name__ == "__main__":
    # 解析命令行参数
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == '--run':
        main()
    elif cmd == '--uninstall':
        uninstall()
    elif cmd == '--install':
        install()
    elif cmd == '--status':
        status()
    else:
        main()







