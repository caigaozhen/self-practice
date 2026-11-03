#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验文件：搞懂 `__name__` 和 `if __name__ == "__main__":`

同一个文件，两种方式运行，输出完全不同。自己试一下：

    方式一（直接运行）      py -3 测试.py
    方式二（被别人 import）  py -3 -c "import 测试"

观察两件事：
    1. 这行 print 是「顶层语句」，两种方式都会执行
    2. 但 main() 只有「直接运行」时才会执行
"""

import winreg

PLAYGROUND = r"Software\WinregPlayground"

print(f"[顶层] 文件被加载了，此刻 __name__ = {__name__!r}")
print()


def dump(path: str) -> None:
    """通用小工具：打印某个键下面所有值。可以直接 import 复用。"""
    print(f"[{path}]")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
        n_sub, n_val, _ = winreg.QueryInfoKey(key)
        print(f"  子键 {n_sub} 个，值 {n_val} 个")
        i = 0
        while True:
            try:
                name, data, vtype = winreg.EnumValue(key, i)
            except OSError:
                break
            shown = data.hex() if isinstance(data, bytes) else data
            print(f"    {name:<24} type={vtype}  {shown}")
            i += 1


def main() -> None:
    print(">>> main() 开始执行了")
    print("    说明：__name__ == '__main__' 这个条件成立了")
    print()

    # 在自建键里读写，不碰 Run，跑完自动清理
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PLAYGROUND) as key:
        winreg.SetValueEx(key, "Greeting", 0, winreg.REG_SZ, "你好，注册表")
        winreg.SetValueEx(key, "Counter", 0, winreg.REG_DWORD, 42)
    dump(PLAYGROUND)

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PLAYGROUND, 0, winreg.KEY_WRITE) as key:
        winreg.DeleteValue(key, "Greeting")
        winreg.DeleteValue(key, "Counter")
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, PLAYGROUND)
    print("\n>>> 玩具键已清理")


# 只有「被直接运行」时 __name__ 才是 "__main__"，
# 被 import 时它等于模块名（"测试"），所以下面的 main() 不会执行。
if __name__ == "__main__":
    main()
