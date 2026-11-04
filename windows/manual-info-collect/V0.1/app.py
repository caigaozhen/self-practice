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

# 检查应用是否安装
def status():
    expected = launcher_command()
    try:
        # 
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN) as key:
            actual, _type = winreg.QueryValueEx(key, APP_NAME)
    except FileNotFoundError:
        actual = None

    print(f"当前状态：{'已安装' if actual else '未安装'}")
    if actual and actual != expected:
        print("当前启动命令与预期启动命令不一致")
        print("预期启动命令：", expected)
        print("当前启动命令：", actual)


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







