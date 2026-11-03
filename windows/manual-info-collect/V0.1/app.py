from datetime import datetime
from pathlib import Path
import sys

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
    python = Path(sys.executable) # Path获取路径，sys.executable获取运行当前文件的脚本解释器的完整路径
    exe = python.with_name("pythonw.exe") # 保留文件目录，只更换文件名
    if not exe.exists():
        exe = python
    script = Path(__file__).resolve() # 当前文件获取绝对路径
    return f'"{exe}" "{script}" --run' # --run 自己指定，此时还没有指定

# 写入用户注册表
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

# main()
# print(launcher_command())
install()






