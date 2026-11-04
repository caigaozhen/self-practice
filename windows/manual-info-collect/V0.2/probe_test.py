import subprocess
import sys
from pathlib import Path

# from是导入模块的语法糖，from模块 import 类名、函数名、变量名
# 例如：from datetime import datetime
# 例如：from pathlib import Path

# subprocess用于启动子进程
# .run()方法的第一个参数是一条命令，推荐使用目前的列表方式实现，最终是 python -c "import tkinter"  
# capture_output=True 代表捕获子进程的标准输出和标准错误输出，否则捕获不到输出，更没有text=True格式转换
# text=True 代表将子进程的标准输出和标准错误输出转换为字符串，而不是字节序列,否则就需要解码decode

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

#r 的返回值是一个对象，包含了子进程的返回码、标准输出、标准错误输出等信息
# returncode 代表子进程的返回码，0代表成功，非0代表失败
# stdout 代表子进程的标准输出，stderr 代表子进程的标准错误输出
# print("返回码:", r.returncode)
# print("stdout:", r.stdout[:200])
# print("stderr:", r.stderr[:200])

if __name__ == "__main__":
    print('当前解释器:', has_tkinter(Path(sys.executable)))
    print('不存在的路径:', has_tkinter(Path(r"C:\no\such\python.exe")))



