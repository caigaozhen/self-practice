# Windows 开机自启与开机时间统计

一个单文件 Python 小工具的完整知识沉淀：从注册表 `Run` 键的写入原理，到用 `GetTickCount64` 反推开机时刻，再到 tkinter 弹窗的坑。全部结论都在本机（Windows 11 + Python 3.14）实测验证过。

## 目录

- [1. 这个工具做了什么](#1-这个工具做了什么)
- [2. 先厘清概念：Windows 其实没有"开机自启"](#2-先厘清概念windows-其实没有开机自启)
- [3. 登录那一刻发生了什么](#3-登录那一刻发生了什么)
- [4. 五种自启动位置](#4-五种自启动位置)
- [5. 为什么写 HKCU 不需要管理员](#5-为什么写-hkcu-不需要管理员)
- [6. 注册表的数据结构：键与值](#6-注册表的数据结构键与值)
- [7. winreg 模块](#7-winreg-模块)
- [8. 用 Run 键实现自启动](#8-用-run-键实现自启动)
- [9. pythonw 为什么没有黑框](#9-pythonw-为什么没有黑框)
- [10. 开机时间怎么算出来](#10-开机时间怎么算出来)
- [11. 完整实现的关键决策](#11-完整实现的关键决策)
- [12. 踩坑清单](#12-踩坑清单)
- [13. 排查工具](#13-排查工具)
- [14. 本机实测记录](#14-本机实测记录)
- [15. 延伸练习](#15-延伸练习)

---

## 1. 这个工具做了什么

`bootstat.py` 一个文件，零第三方依赖：

1. 把自己写进注册表 `Run` 键，实现登录后自动运行（不需要管理员）
2. 每次运行记录一次：开机时刻、启动耗时
3. 右下角弹一个窗口显示统计，8 秒后自动消失
4. 数据存 `%LOCALAPPDATA%\BootStat\boots.json`

```
bootstat/
├── bootstat.py        # 主程序（约 330 行）
├── 测试.py            # 练习脚本：演示 __name__ 与注册表读写，可安全运行
├── install.bat        # 双击安装自启动
├── uninstall.bat      # 双击移除自启动
└── README.md          # 本文档
```

常用命令：

```bash
python bootstat.py --install     # 安装自启动（幂等，可重复执行）
python bootstat.py --uninstall   # 移除自启动
python bootstat.py --status      # 命令行看统计
python bootstat.py --run         # 记录一次并弹窗（默认行为）
python bootstat.py --run --no-popup   # 只记录不弹窗
```

---

## 2. 先厘清概念：Windows 其实没有"开机自启"

绝大多数人说的"开机自启"，实际是**登录自启**。

因为从 Vista 起程序默认跑在**用户会话**里，而会话要等你输完密码才会创建。所以 `Run` 键里的程序不是"开机就跑"，而是"你登录后立刻跑"。

分界线在这：

| 需求 | 触发时机 | 用什么 |
|---|---|---|
| 用户登录后跑一个带界面的程序 | 登录后 | `Run` 键 / 启动文件夹 |
| 登录前就要跑，不需要界面 | 开机时 | 服务（SCM）/ 任务计划"开机触发" |
| 登录后延迟一会儿再跑 | 登录后 + 延迟 | 任务计划 |

### 快速启动带来的两个认知陷阱

Win10/11 默认开启**快速启动（Fast Startup）**。点"关机"时，Windows 并不是完全断电重启，而是把内核会话休眠到 `hiberfil.sys`；下次按电源是"恢复 + 重新登录"。这带来两个后果：

1. **"关机再开机"不等于冷启动。** 你要完整的冷启动，得选"重启"，因为"重启"永远走完整的关机和启动流程，会绕过快速启动。
2. **系统运行时长可能不归零。** 快速启动下，某些计数器会延续上次的值。这直接影响第 10 节的开机时间算法，是那个方案的已知精度边界。

---

## 3. 登录那一刻发生了什么

```
① 内核与服务启动          ← 没有桌面，服务以 SYSTEM 身份运行
        ↓
② Winlogon 显示登录界面   ← 你的进程空间还不存在
        ↓
③ 用户会话建立            ← 加载 HKCU 配置单元，生成用户令牌
        ↓
④ explorer 扫描自启动点   ← 读 Run 键、启动文件夹，逐个 CreateProcess
        ↓
⑤ 你的程序被拉起来        ← 注册表里那条命令行被执行的一刻
```

关键点是第 ④ 步：`Run` 键是**由 `explorer.exe` 读取并执行的**，而且它只在你登录时扫一遍。这意味着：

- 装完自启动不会立刻生效，必须注销或重启
- `explorer.exe` 崩溃重启**不会**重跑这些条目（一次登录只跑一次）
- 你在任务管理器里"禁用"它，也不需要重启就能生效，因为读的是另一份状态（见第 12 节）

---

## 4. 五种自启动位置

| 位置 | 触发时机 | 写它要管理员 | 典型场景 |
|---|---|---|---|
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | 该用户登录 | 不需要 | 用户级小工具（本项目） |
| `HKLM\Software\Microsoft\Windows\CurrentVersion\Run` | 任何用户登录 | 需要 | 全机器生效，如输入法、显卡驱动 |
| 启动文件夹 `shell:startup` | 该用户登录 | 不需要 | 绿色软件、快捷方式，肉眼可见 |
| 任务计划程序 | 登录或开机，可延迟 | 看配置 | 要延迟启动、要最高权限、要定时 |
| 服务（SCM） | 开机，登录前 | 需要 | 无界面后台常驻，唯一真正的开机自启 |

### 几个容易忽略的变体

- **`RunOnce`**：执行一次后自动删除自身的值，适合"只跑一次"的初始化任务。它是 `Run` 的**兄弟键**，不是子键。
- **`RunOnce` 的前缀**（少用但值得知道）：`!` 表示先把值删掉再执行（失败也不重试），`*` 表示安全模式下也运行。
- **`HKLM\...\WOW6432Node\...\Run`**：32 位程序写 `HKLM\Software` 时会被重定向到这里，见第 7 节的 32/64 位视图。
- **`RunServices`**：Win9x 时代的遗留，NT 内核上无效，别用。

---

## 5. 为什么写 HKCU 不需要管理员

注册表在逻辑上是一棵树，但**权限不在"树"上，而在"配置单元（hive）"上**。

| 根键 | 背后是 | 谁能写 |
|---|---|---|
| `HKEY_CURRENT_USER` | `C:\Users\你\NTUSER.DAT` | 这个文件属于你，ACL 给你完全控制 → **随便写** |
| `HKEY_LOCAL_MACHINE` | 机器级配置（`SYSTEM`、`SOFTWARE` 等配置单元） | 需要 `Administrators` 组成员资格 → **弹 UAC** |
| `HKEY_USERS` | 所有用户配置单元的集合 | 别人的 hive 要提权 |
| `HKEY_CLASSES_ROOT` | `HKLM\Software\Classes` 与 `HKCU\Software\Classes` 的合并视图 | 看具体写到哪一侧 |
| `HKEY_CURRENT_CONFIG` | 当前硬件配置文件的别名 | 基本只读 |

反过来看，这也是为什么恶意软件偏爱 `HKCU\...\Run`：不需要提权就能持久化。因此**安全软件会重点监控这个键的写入**，你自己写的时候如果遇到杀软弹提示，是正常现象。

---

## 6. 注册表的数据结构：键与值

树上只有两种节点，分清它就理解了一半。

| | 键（Key） | 值（Value） |
|---|---|---|
| 类比 | 文件夹 | 文件夹里的文件 |
| 特征 | 可以再套子键，不能直接存数据 | 是叶子，不能再分 |
| 怎么定位 | 路径字符串，如 `\Software\...\Run` | 「键 + 值名」，如 `Run` 里的 `BootStat` |
| Python 里 | 一个 `PyHKEY` 句柄对象 | 调用函数时传值名 |

**值没有独立路径。** 你不能"打开 `Run\BootStat` 这个键"，只能说"打开 `Run` 这个键，然后取名叫 `BootStat` 的值"。

### 实操教训：左边树只显示键

用 regedit 打开 `HKCU\...\CurrentVersion\Run` 时，这个键的真实构成是：

```
子键 1 个  → QQDisabled        ← 左边树里唯一能看到的东西
值   6 个  → OneDrive, MicrosoftEdgeAutoLaunch_..., iFlyInput,
             org.yuanli.utools, DingTalk, BootStat
```

`BootStat` 是**值**，所以它只出现在**右侧**窗口，左侧树里永远找不到它。第一次找的时候很容易在左边的树里翻半天。

另外，`(默认)` 是每个键天生自带的值，名称是空字符串 `""`。

### 枚举顺序不等于显示顺序

`winreg.EnumValue` 按**索引顺序**遍历，返回的是存储顺序，不保证字母序；regedit 在显示时自己排了一遍。

**结论：不要依赖枚举顺序。** 要排序自己 `sorted()`，不要假设"第一个是默认值"。

---

## 7. winreg 模块

### 它是什么

- Python **标准库**里的内建模块（不是第三方包，`pip` 装不到也卸不掉）
- 它是**内建 C 模块**，编译进了 `python.exe`，所以连 `__file__` 都没有
- 本质是 Win32 注册表 API（`advapi32.dll` 里的 `RegOpenKeyEx` 等）的薄包装，没有自己的数据模型

```python
>>> import winreg, sys
>>> 'winreg' in sys.builtin_module_names
True
>>> winreg.__file__
AttributeError: module 'winreg' has no attribute '__file__'
```

### 常量对照

```python
HKEY_CLASSES_ROOT      = 0x80000001    # 实际是 Win32 预定义句柄 0xFFFFFFFF80000000
HKEY_CURRENT_USER      = 0x80000001
HKEY_LOCAL_MACHINE     = 0x80000002
HKEY_USERS             = 0x80000003
HKEY_CURRENT_CONFIG    = 0x80000005

REG_SZ          = 1     # 普通字符串
REG_EXPAND_SZ   = 2     # 字符串，执行时展开 %VAR%
REG_BINARY      = 3     # 原始字节，Python 里是 bytes
REG_DWORD       = 4     # 32 位整数，Python 里是 int
REG_MULTI_SZ    = 7     # 字符串列表
REG_QWORD       = 11    # 64 位整数
```

### API 对照表

| 你要干的事 | winreg | Win32 API |
|---|---|---|
| 打开已存在的键 | `OpenKey` | `RegOpenKeyEx` |
| 创建键，或打开它 | `CreateKey` | `RegCreateKeyEx` |
| 读一个值 | `QueryValueEx` | `RegQueryValueEx` |
| 写一个值 | `SetValueEx` | `RegSetValueEx` |
| 遍历子键 | `EnumKey` | `RegEnumKeyEx` |
| 遍历值 | `EnumValue` | `RegEnumValue` |
| 删值 / 删键 | `DeleteValue` / `DeleteKey` | `RegDeleteValue` / `RegDeleteKey` |
| 关闭句柄 | `Close`（或 `with` 自动） | `RegCloseKey` |
| 查子键数/值数 | `QueryInfoKey` | `RegQueryInfoKey` |

### 最小可用示例

```python
import winreg

PATH = r"Software\WinregPlayground"

# 写：CreateKey 默认带 KEY_WRITE 权限
with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PATH) as key:
    winreg.SetValueEx(key, "Greeting", 0, winreg.REG_SZ, "你好")
    winreg.SetValueEx(key, "Counter",  0, winreg.REG_DWORD, 42)

# 读：OpenKey 默认只有 KEY_READ
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PATH) as key:
    data, vtype = winreg.QueryValueEx(key, "Greeting")   # ('你好', 1)
    data, vtype = winreg.QueryValueEx(key, "Counter")    # (42, 4)

# 遍历所有值
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PATH) as key:
    i = 0
    while True:
        try:
            name, data, vtype = winreg.EnumValue(key, i)
        except OSError:      # 越界就是遍历结束，这是正常终止方式
            break
        print(name, vtype, data)
        i += 1

# 删（DeleteKey 只能删空键）
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PATH, 0, winreg.KEY_WRITE) as key:
    winreg.DeleteValue(key, "Greeting")
    winreg.DeleteValue(key, "Counter")
winreg.DeleteKey(winreg.HKEY_CURRENT_USER, PATH)
```

可运行版本见 `测试.py`，它只操作 `HKCU\Software\WinregPlayground` 这个自建键，跑完会自己清理干净。

### 异常语义（重要）

**读不到时它抛异常，不返回 `None`。**

| 情况 | 异常 |
|---|---|
| 键不存在（`OpenKey`） | `FileNotFoundError`（`WinError 2`） |
| 值不存在（`QueryValueEx`） | `FileNotFoundError` |
| 遍历越界（`EnumValue`） | `OSError` |
| 权限不足 | `PermissionError`（`WinError 5`） |

所以读之前要么 `try/except FileNotFoundError`，要么先用 `QueryInfoKey` 探数量。

### 两个必知的坑

**① `OpenKey` 默认只给读权限。** 想写必须显式传 `KEY_WRITE`：

```python
winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE)
```

`CreateKey` 例外，它默认就带写权限。

**② 64 位系统上有两套视图。** 32 位 Python 访问 `HKLM\Software` 时会被**静默重定向**到 `HKLM\Software\WOW6432Node`。同一段代码，32 位和 64 位解释器跑出来的结果可能完全不同。要显式指定：

```python
winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
               winreg.KEY_READ | winreg.KEY_WOW64_64KEY)   # 强制看 64 位视图
```

**③ 这个模块只在 Windows 上存在。** 跨平台代码要 `try: import winreg / except ImportError:` 做降级。

---

## 8. 用 Run 键实现自启动

### 五行核心代码

```python
import winreg

REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
cmd = f'"{pythonw_exe}" "{script_path}" --run'

with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_RUN) as key:
    winreg.SetValueEx(key, "BootStat", 0, winreg.REG_SZ, cmd)
```

逐参数：

- `HKEY_CURRENT_USER` — 根键，写自己的 hive，不需要管理员
- `REG_RUN` — 相对路径，不含根键名
- `"BootStat"` — **值名**，就是 regedit 右侧「名称」列那一项
- `0` — 保留位，必须是 0
- `winreg.REG_SZ` — 数据类型
- `cmd` — **一整个命令行字符串**

移除就是删值：

```python
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_SET_VALUE) as key:
    winreg.DeleteValue(key, "BootStat")
```

### 关键认知：值是命令行，不是路径

系统拿到这个值之后直接丢给 `CreateProcess`，**不做参数拆分解析**。所以：

```
C:\Program Files\My App\app.exe -start      ✗ 系统会尝试运行 C:\Program.exe
"C:\Program Files\My App\app.exe" -start    ✓ 引号把路径围起来
```

路径带空格不加引号是老牌提权漏洞的经典成因：Windows 会按空格逐个试探，先在 `C:\` 下找 `Program.exe`。所以**每一段带空格的路径都要单独加引号**，本项目注册表里存的是：

```
"C:\...\Python314\pythonw.exe" "D:\...\bootstat\bootstat.py" --run
```

### REG_SZ 与 REG_EXPAND_SZ

本机 `HKLM\...\Run` 里有个反例可以直接对照：

```
SecurityHealth   type=2   %windir%\system32\SecurityHealthSystray.exe    ← 能展开
RtkAudUService   type=1   "C:\WINDOWS\System32\DriverStore\...\x.exe" -b  ← 不展开
```

`REG_SZ`（type=1）**不展开**环境变量，写了 `%windir%` 就是字面量，系统会拿着这串字符去找文件然后失败。要用环境变量必须写 `REG_EXPAND_SZ`（type=2）：

```python
winreg.SetValueEx(key, "BootStat", 0, winreg.REG_EXPAND_SZ,
                  r"%LOCALAPPDATA%\BootStat\run.bat")
```

### 为什么是"安装"却"装"不出任何文件

`Run` 键不是"软件装在哪里"的登记表，它是**"登录时请执行这条命令"的待办清单**。

```
系统读清单 → CreateProcess("pythonw.exe" "bootstat.py" --run)
          → 解释器读源码 → 执行 → 写数据文件
```

类比：便签上写"明早 8 点叫我"，便签本身不是闹钟，它只是一条指令；`pythonw.exe` 才是闹钟。

这解释了一连串现象：

- 为什么没有安装目录、没有 `.exe`、控制面板里也找不到它
- 为什么"卸载"不用跑卸载程序，删掉那行字就行
- 为什么它会出现在任务管理器的"启动应用"页，却不出现在"应用"列表里

（"设置 → 应用 → 已安装的应用"那份列表来自另一个位置：`HKLM\...\Uninstall` 和 `HKCU\...\Uninstall` 下的登记项，跟 `Run` 键无关。）

### 一个必须知道的脆弱性

注册表里存的是**绝对路径**。脚本文件一改名、一移动、一删除，注册表那行就指向了不存在的文件，而 `pythonw.exe` 没有控制台，**失败是完全静默的**。

诊断方法：看数据文件里有没有当天的记录。没有记录，就是没跑起来。

正规软件会把文件放进 `Program Files` 这类稳定目录，并在安装时做完整性校验，本质上就是在对付这个"绝对路径脆弱"的问题。

---

## 9. pythonw 为什么没有黑框

由 PE 文件头里的 `Subsystem` 字段决定：

| 值 | 常量 | 含义 |
|---|---|---|
| 2 | `IMAGE_SUBSYSTEM_WINDOWS_GUI` | GUI 程序，不分配控制台 → **没有黑框**（`pythonw.exe`） |
| 3 | `IMAGE_SUBSYSTEM_WINDOWS_CUI` | 控制台程序，分配控制台窗口 → **有黑框**（`python.exe`） |

`pythonw.exe` 和 `python.exe` 是同一个解释器，只是链接时声明的子系统不同。

### 代价：stdout/stderr 没有接收方

用 `pythonw` 跑的进程：

- `print()` 的输出**直接丢弃**
- 未捕获的异常**不弹任何提示**，进程安静地死掉
- 你不能靠 `>>` 重定向去看它的输出

所以这类程序必须有日志。本项目所有输出走弹窗，`--no-popup` 时走 `print`（那时是人手动在终端里跑，有控制台）。更稳妥的做法是加一个 `logging.FileHandler`：

```python
import logging
logging.basicConfig(filename="bootstat.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
```

---

## 10. 开机时间怎么算出来

### 思路：现在减去已运行时长

```python
import ctypes
from datetime import datetime, timedelta

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.GetTickCount64.restype = ctypes.c_ulonglong   # 这一行不能省

uptime = _k32.GetTickCount64() / 1000.0            # 秒
boot_at = datetime.now() - timedelta(seconds=uptime)
```

`GetTickCount64` 返回系统启动至今的毫秒数，减去它就是开机时刻。优点：零第三方依赖（不用 `psutil`），一次系统调用，快。

### 陷阱：ctypes 默认返回类型是 32 位有符号整数

`ctypes` 没声明 `restype` 时按 `c_int`（32 位有符号）处理，于是 64 位返回值被截断：

```
2^31 毫秒 = 2147483648 ms ≈ 24.85 天
```

**开机超过 24.85 天后，返回值变成负数**，算出的"开机时刻"会跑到未来去。这是个很难发现的 bug：程序刚写好时测试完全正常，一个月后才出错。

必须显式声明：

```python
_k32.GetTickCount64.restype = ctypes.c_ulonglong
```

对比一下：`GetTickCount`（32 位版）在 49.7 天回绕，`GetTickCount64` 的 64 位可表示约 5.8 亿年，不会回绕。

### 另一种算法：WMI 的 LastBootUpTime

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object LastBootUpTime
```

```python
import subprocess
subprocess.run(["powershell", "-c",
    "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime"])
```

它返回系统自己记录的启动时间，精度到秒。缺点是要起一个 PowerShell 进程（几百毫秒），且受第 2 节说的快速启动影响更明显。所以本项目用 `GetTickCount64`。

### 已知精度边界

| 现象 | 对结果的影响 |
|---|---|
| 计数器精度约 15.6 ms | 秒级误差，可忽略 |
| 睡眠/休眠时间可能被计入 | 睡眠后算出的开机时刻会偏早 |
| 快速启动（关机→开机） | 计数器可能不归零，导致开机时刻严重偏早 |
| "重启" | 永远是完整启动，不受快速启动影响 |

也就是说，"开机时刻"这个数在**每次都是冷启动或重启**的机器上准确，在经常"关机 + 快速启动开机"的机器上会偏早。这是这套方案的固有边界，不是 bug。

### 顺带得到的一个指标

`GetTickCount64` 在程序启动那一刻的值，就是**"从上电到程序被拉起来花了多少秒"**，可以当作启动耗时的代理指标。本项目记录的 `startup_seconds` 就是它。注意它包含"等你输密码"的时间，所以不是纯硬件启动速度。

---

## 11. 完整实现的关键决策

### 数据存哪里

`%LOCALAPPDATA%\BootStat\boots.json`，不是脚本同级目录。理由：

- 脚本可能放在只读位置（`Program Files`、U 盘）
- `AppData\Local` 是这类"用户本机数据"的标准位置
- 卸载时删目录即可，不污染程序目录

写入用"临时文件 + 原子替换"，避免写一半断电导致 JSON 损坏：

```python
tmp = path.with_suffix(".tmp")
tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(path)
```

读的时候文件损坏就当空数据，**绝不能因为数据坏了就阻断启动**。

### 怎么去重

同一次开机可能被触发多次（比如你手动 `--run` 又跑了一遍）。用「开机时刻取整到分钟」作为 key：

```python
key = boot_at.strftime("%Y-%m-%d %H:%M")
for rec in reversed(data["boots"][-20:]):
    if rec.get("key") == key:
        return rec, False        # 已记录，跳过
```

不需要额外的状态文件。

### 界面必须有兜底

`tkinter` 不是所有 Python 发行版都有（比如某些精简版、以及本机 WorkBuddy 内置的那个 3.13 就缺）。所以：

```python
try:
    import tkinter as tk
except Exception:
    msgbox("\n".join(lines))     # 退回 ctypes 调 MessageBoxW
    return
```

进一步的做法是**探测并挑选解释器**：安装时遍历候选解释器，用 `子进程 -c "import tkinter"` 探测哪个可用，注册表里就写那个的 `pythonw.exe`。

### 单个实例、异常安全

`--run` 模式下要保证任何异常都不能让弹窗挡住用户：

```python
try:
    show_popup(lines)
except Exception:
    pass          # 弹窗失败就算了，数据已经写盘
```

---

## 12. 踩坑清单

| # | 坑 | 表现 | 解法 |
|---|---|---|---|
| 1 | 左边树只显示键 | 在 regedit 左侧找不到自己写的东西 | 值是叶子，只在右侧显示 |
| 2 | 路径不加引号 | 带空格路径执行错程序，或静默失败 | 每段路径单独加引号 |
| 3 | `REG_SZ` 写 `%VAR%` | 变量不展开，找不到文件 | 用 `REG_EXPAND_SZ` |
| 4 | 装完不生效 | 注册表有值但程序没跑 | `explorer` 只在登录时扫一次，注销或重启 |
| 5 | `pythonw` 静默失败 | 什么都没发生，也没有报错 | 写日志文件；靠数据文件有无当天记录反推 |
| 6 | `restype` 没声明 | 开机 24.85 天后时间算错 | `restype = ctypes.c_ulonglong` |
| 7 | `EnumValue` 越界 | 以为出错，其实只是遍历结束 | 捕获 `OSError` 作为正常终止 |
| 8 | `DeleteKey` 有内容 | 抛 `OSError` | 先删空所有值和子键 |
| 9 | `OpenKey` 没有写权限 | `PermissionError` | 显式传 `KEY_WRITE` |
| 10 | 32/64 位视图 | 同一段代码读到不同内容 | `KEY_WOW64_64KEY` / `KEY_WOW64_32KEY` |
| 11 | 依赖枚举顺序 | 顺序和 regedit 显示不一致 | 自己 `sorted()` |
| 12 | 任务管理器"禁用" | 注册表值还在，但程序不跑 | 见下方说明 |

### 关于"禁用"的机制

任务管理器里的"禁用"**不会删除注册表值**，而是在另一个位置写一个二进制标记：

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run
```

本机实测（`REG_BINARY`，转 hex 后）：

```
iFlyInput      03 000000 1bf58c04f0cdda01     ← 启用，首字节 3，后 8 字节是 FILETIME
OneDrive       03 000000 37f275d62ac1d901     ← 启用
Docker Desktop 01 000000 0000000000000000     ← 禁用，首字节 1
夸克网盘        02 000000 0000000000000000     ← 启用，首字节 2 无时间戳
```

规律：**首字节 `2` 或 `3` = 启用（`3` 带时间戳），`1` = 被用户禁用。**

几点补充：

- 这个格式微软**没有公开文档**，是逆向出来的，不同版本可能有差异，**不要手改**
- 没有条目 = 默认启用（新写入的项不会立刻出现在这里）
- 这里出现的项**不一定还存在于 `Run` 键**。本机 `Docker Desktop`、`夸克网盘`、`水豚鼠标助手` 都在 `StartupApproved` 里有记录，但 `HKCU` 的 `Run` 键里已经没有它们了——说明这张表是**历史记录**，`Run` 键才是真相
- 所以"注册表明明有却不运行"，第一步应该查这里

---

## 13. 排查工具

| 工具 | 怎么看 | 适合 |
|---|---|---|
| 注册表编辑器 | `Win+R` → `regedit`，地址栏粘路径 | 看值、改值、删值 |
| 任务管理器 | `Ctrl+Shift+Esc` → 启动应用 | 看启用状态、启动影响 |
| 启动文件夹 | `Win+R` → `shell:startup` | 看快捷方式类自启动 |
| Autoruns | Sysinternals 工具 | 一次性列出所有持久化位置（十几处） |
| PowerShell | `Get-ItemProperty 'HKCU:\...\Run'` | 脚本化检查 |
| Python | `winreg.EnumValue` 循环 | 写工具、批量审计 |

两个小技巧：

**让 regedit 直接定位到某个键。** regedit 会记住上次关闭时的位置，这个位置存在：

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Applets\Regedit → LastKey
```

写入目标路径（格式如 `计算机\HKEY_CURRENT_USER\Software\...`），下次打开 regedit 就落在那儿。

**任务管理器里显示的名字不是值名。** 它按可执行文件的版本信息命名，所以指向 `pythonw.exe` 的条目会显示成 `Python`，而不是你写的 `BootStat`。看到 `Python` 别以为是装错了。

---

## 14. 本机实测记录

环境：Windows 11 + Python 3.14（`C:\Users\29242\AppData\Local\Programs\Python\Python314`），另一处 Python 3.13 为 WorkBuddy 内置，**缺 tkinter**。

### 注册表实际写入的值

```
"C:\Users\29242\AppData\Local\Programs\Python\Python314\pythonw.exe"
 "D:\workbuddy--\workspace\2026-10-29-17-59-24\bootstat\bootstat.py" --run
```

### 实测自动运行记录

```json
{
  "boots": [
    {"boot_at": "2026-10-29 18:20:51", "startup_seconds": 64.5},
    {"boot_at": "2026-10-30 08:25:35", "startup_seconds": 54.4}
  ]
}
```

两次真实开机、两次被系统自动拉起，`startup_seconds` 稳定在 55~65 秒区间，说明链路可用。第二次（次日早上）证明它是**持续生效**的，不是一次性的偶发。

### 环境差异导致的一个坑

本机有两个 Python：

| 解释器 | tkinter | 结果 |
|---|---|---|
| `py -3` → Python314 | 有（TkVersion 9.0） | 右下角自绘弹窗 |
| WorkBuddy 内置 3.13 | **无** | 退化成系统 `MessageBoxW` 对话框 |

这直接导致了 `best_interpreter()` 那套探测逻辑：安装时必须挑一个真能 `import tkinter` 的解释器，否则用户会看到一个丑陋的系统对话框还以为成功了。

---

## 15. 延伸练习

按难度排：

1. **改行为**：把弹窗改成"只弹提醒不统计"，或者加一个"该休息了"的定时提示
2. **加日志**：用 `logging` 把每次启动、异常都写到文件，然后故意把脚本路径改错，验证你能不能从日志发现失败
3. **换位置**：改成用启动文件夹方案（`shell:startup` 放快捷方式），对比两种方案的优缺点
4. **延迟启动**：改用任务计划程序，设置"登录后延迟 30 秒"，解决开机瞬间抢资源的问题
5. **打包成 exe**：用 PyInstaller 打成单文件 exe，让目标机器不需要装 Python。注意这时 `sys.executable` 指向的是 exe 自己，`launcher_command()` 的逻辑要重写
6. **升级数据层**：把 `boots.json` 换成 SQLite，加一个统计"平均开机时间""最早/最晚开机"的查询
7. **加界面**：用 tkinter 做一个查看历史的窗口，带折线图（可以用 `tkinter.Canvas` 手绘，不必上 matplotlib）

---

## 参考

- [Run and RunOnce Registry Keys — Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys)
- [winreg — Windows registry access — Python docs](https://docs.python.org/3/library/winreg.html)
- [RegOpenKeyExW — Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/winreg/nf-winreg-regopenkeyexw)
- [GetTickCount64 — Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-gettickcount64)
- 《Windows Internals》第 7 版，第 11 章（注册表机制）、第 12 章（启动与登录）
- Sysinternals **Autoruns**：一次列出所有自启动位置
