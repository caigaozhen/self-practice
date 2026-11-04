# V0.1 · 写入注册表并启动自己

> **一句话目标**：让一个 Python 脚本把自己写进注册表自启项，注销重登后能被自动拉起；拉起后往文件里追加一行时间戳。
>
> **状态**：✅ 已完成（2026-11-04）。本文档既是任务说明，也是这一版的实现记录与复盘。

这一版不采集任何东西，只证明一件事：**自启这条路能走通**。

---

## 一、成品是什么

`app.py` 约 85 行，五个函数 + 一段入口分发，无第三方库。

| 函数 | 职责 |
|---|---|
| `main()` | 被拉起后干的事：往 `run.log` 追加一行时间戳 |
| `launcher_command()` | 算出"该写进注册表的那串字符串" |
| `install()` | 把上面那串写进 `HKCU\...\Run` |
| `uninstall()` | 删除那个值（幂等） |
| `status()` | 读回实际值，与应写值比对 |

三个常量：

```python
REG_RUN  = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ManualInfoCollect"                       # 同时用作注册表值名
LOG_FILE = Path(__file__).parent / "run.log"         # 与脚本同目录
```

> 正式版把日志放到 `%APPDATA%\InfoCollect\`。V0.1 故意放脚本目录，为的是**一眼能看到它**，不用去翻系统目录。

### 实测证据

```
$ py -3 app.py --install
安装成功

$ py -3 app.py --status
当前状态：已安装                     ← 没有"不一致"告警

注册表实际值：
"C:\...\Python314\pythonw.exe" "F:\...\V0.1\app.py" --run
类型: 1 (REG_SZ)

模拟开机（原样执行注册表里那串命令）：
run.log 行数：17 → 18
最后一行：2026-11-04 10:07:55程序开始运行了
```

最后一条是关键——**注册表 → 命令 → `--run` → `main()` → 写日志**，整条链路在无人干预下走通。

---

## 二、四个关键实现点

### 1. `launcher_command()`：拼一串"开机时能被系统执行的命令"

```python
python = Path(sys.executable)                  # 谁在跑我
exe    = python.with_name("pythonw.exe")       # 同目录的无窗口兄弟
if not exe.exists():
    exe = python                               # 没 pythonw 就退回 python
script = Path(__file__).resolve()              # 脚本绝对路径
return f'"{exe}" "{script}" --run'
```

三个要点，缺一个都会静默失败：

- **必须 `pythonw.exe`**：`python.exe` 是 Console 子系统，开机弹黑窗口，关掉窗口进程就死。`pythonw` 是 GUI 子系统，不分配控制台。
- **两段路径各自一对引号**：`--run` 放在引号外。整串交给 `CreateProcess` 时按空格切分，引号位置错了参数会被当成路径的一部分。
- **`--run` 只能是这个值**。原因见"坑 ①"，这是本版最容易错的一行。

### 2. `install()`：写 `REG_SZ`

```python
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_WRITE) as key:
    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
```

- `CreateKeyEx` = 存在就打开、不存在就创建，天然幂等，重复执行不报错
- `KEY_WRITE` 够用；更精确的写法是 `KEY_SET_VALUE`（只申请"写值"，不多要建子键的权限）
- 值类型必须是 `REG_SZ`。`REG_EXPAND_SZ` 是给 `%APPDATA%` 这类变量展开用的，语义不同

### 3. `uninstall()`：把"没有"当成成功

```python
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_WRITE) as key:
        winreg.DeleteValue(key, APP_NAME)
    print("删除成功")
except FileNotFoundError:
    print("本来就没有安装，无需删除")
```

`DeleteValue` 找不到值时抛 `FileNotFoundError`。这不是错误——对调用者而言"删完之后没有这个值"与"本来就没有"结果一致。**按成功处理，这就是幂等。**

### 4. `status()`：把两个字符串并排比

```python
actual, _type = winreg.QueryValueEx(key, APP_NAME)
```

- `QueryValueEx` 返回**元组** `(值, 类型编号)`，解包才能拿到字符串本身
- `OpenKey` 后两个参数有默认值：`reserved=0`、`access=KEY_READ`，所以只读时可以省略
- 但 `uninstall` 里**不能省** `access`，删值属写操作，默认只读句柄会得到 `PermissionError [WinError 5]`
- 权限只在"打开句柄"那一刻检查一次，之后所有操作跟着句柄走——这就是 `QueryValueEx` 不需要权限参数的原因

**这一步是全版性价比最高的设计**：它用内部一致性检查，无需依赖外部工具，就能发现"注册表里的值与当前代码预期不符"。本版开发过程中它抓到过一次真实的参数写错。

---

## 三、入口分发

```python
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if   cmd == "--run":       main()
    elif cmd == "--uninstall": uninstall()
    elif cmd == "--install":   install()
    elif cmd == "--status":    status()
    else:                      main()
```

| 参数 | 谁用 | 行为 |
|---|---|---|
| `--run` | **系统/自启**，由注册表那串带进来 | 写日志 |
| `--install` | 人敲 | 装机 |
| `--uninstall` | 人敲 | 卸载 |
| `--status` | 人敲 | 查状态 |
| 无参数 | 人敲 / 双击 | 等同 `--run`（兜底） |

`__name__` 是解释器自动赋值的变量：直接运行时为 `"__main__"`，被别的文件 `import` 时为模块名。这行 `if` 的作用是**"只在被直接运行时才执行分发"**，避免以后拆模块时 `import` 产生副作用。

---

## 四、真实踩过的六个坑

**① 把 `--run` 写成了别的值（本版最大陷阱，连错三次）**

`launcher_command()` 的返回值决定"**开机时执行什么**"，它只能是"干活"的入口：

| 写错成 | 开机时的实际行为 |
|---|---|
| `--install` | 每次开机重装一遍自己，不写日志 |
| `--uninstall` | **开机第一件事是把自启项删掉**，从此不自启 |
| `--status` | 打印一句状态然后退出，永远不会写日志 |

三种都语法合法、程序也能跑起来，只是**语义全错**，而且失败完全静默。记住：这一行不是"随便填个参数"，它和"给人敲的命令"是两类东西。

**② 参数名逐字符比较，差两个横线就是另一个世界**

```powershell
py -3 app.py status      → argv[1] = "status"    → 不匹配 "--status" → 落到 else → main()
py -3 app.py --status    → argv[1] = "--status"  → 正确匹配
```

现象是"我明明执行的是 status，怎么跑起了 main"。**根因不是调错函数，是一个分支都没匹配上，被 `else` 兜住了。** 两处必须逐字符一致（大小写、横线数量都敏感）。

**③ `sys.executable` 是 `str`，不是 `Path`**

```python
python = sys.executable                     # str
exe = python.with_name("pythonw.exe")       # AttributeError: 'str' object has no attribute 'with_name'
```

必须 `Path(sys.executable)` 包一层。Python 是动态类型，类型由赋给它的值决定，写错要到运行时才炸。

**④ 缺 import 报的是 `NameError`，不是 `ImportError`**

```
NameError: name 'Path' is not defined
```

Python 逐行执行，走到 `Path(...)` 那一刻才发现"不认识这个名字"。判断一个名字要不要导入：`print`/`len`/`open` 这类内置的不需要；`Path`、`datetime`、`winreg` 属于某个模块，必须导入。

**⑤ `reg query` 在本机不可用**

`reg.exe` 被环境的程序黑名单拦截（Security Center → Command Security → Program Blacklist），不重试、不绕过。改用：

```powershell
Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name ManualInfoCollect
```

或直接用 Python 读（更通用，与代码走同一条 API 路径）：

```python
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN) as k:
    print(winreg.QueryValueEx(k, "ManualInfoCollect"))
```

**⑥ `print` 在 `pythonw` 下的隐患（本版不修，V0.3 解决）**

无控制台时 `sys.stdout` 为 `None`，`print` 会抛 `AttributeError`。但 `file.write` 写在它之前，**日志已经落盘**，所以不影响自启验证。

> 一个实际观察：从终端里 `subprocess` 拉起 `pythonw.exe` 时，子进程会**继承**父进程的输出句柄，此时 `print` 反而能工作（退出码 0）。真正开机由 explorer 启动、没有可继承的控制台，才会失败。这意味着"在终端里模拟成功"与"真实开机"存在细微差异，验证时以 `run.log` 是否新增为准，不要以有没有报错为准。

---

## 五、验收结果

| 验收项 | 结果 |
|---|---|
| `--install` 后注册表出现值，类型 `REG_SZ` | ✅ 已确认 |
| 值内容为 `"…pythonw.exe" "…app.py" --run` | ✅ 已确认 |
| `--status` 的应写值与实际值完全一致 | ✅ 已确认 |
| `--uninstall` 后值消失；再次执行不报错 | ✅ 已确认 |
| 执行那串命令后 `run.log` 多一行 | ✅ 已确认（17 → 18 行） |
| 注销重登后 `run.log` 自动多一行 | ✅ 你已确认（复核方式：看最后一行时间戳是否为登录时刻） |

---

## 六、与正式版的差异（V0.1 有意简化）

| 项 | V0.1 | 正式版 | 为什么这样简化 |
|---|---|---|---|
| 日志位置 | 脚本同目录 `run.log` | `%APPDATA%\InfoCollect\` | 学习期要"一眼看到"，正式版要"数据与代码分离" |
| 输出方式 | `print` | `logging` + 轮转 | 无控制台程序必须有文件日志，V0.3 补 |
| 异常兜底 | 无 | `sys.excepthook` | 同上 |
| 单实例 | 无 | `CreateMutexW` | 自启 + 手动启动会撞车，V0.4 补 |
| 解释器挑选 | 直接用 `sys.executable` | 挑带 tkinter 的解释器 | V0.1 不弹 GUI，用不上 |
| 失效检测 | 只比字符串 | 判断路径是否存在 | V0.2 补 |
| 自启参数 | `--run` | `LAUNCH_ARGS = "tray"` 常量 | 同一思想：单点定义，两处引用 |

---

## 七、完成后你应当能回答

- 为什么写 `HKCU` 不需要管理员，写 `HKLM` 需要？
- 为什么自启命令里必须是 `pythonw.exe` 而不是 `python.exe`？
- 为什么 `launcher_command()` 里的参数只能是 `--run`，写成 `--install` 会怎样？
- 为什么"值不存在"这种删除结果要算成功？
- 为什么 `QueryValueEx` 不需要传权限参数？
- `if __name__ == "__main__":` 如果去掉，会出现什么问题？

---

## 八、下一步：V0.2

V0.1 能"装得上、跑得起来"，但还缺三层抗打击能力：

1. **幂等性**：重复 `install` 不残留、重复 `uninstall` 不报错（部分已有，需系统性确认）
2. **解释器挑选**：源码形态下 `sys.executable` 可能指向没有 tkinter 的解释器
3. **失效检测**：`status` 现在只比字符串；如果注册表里的路径已被删除，它仍会报"已安装"，但实际上开机一定失败

第 3 条是这个项目里最容易被忽略、也最难排查的一类问题：**自启失败是静默的**。

参考文件：`windows/info-collect/win/autostart.py`（整个自启逻辑约 220 行）。对照时重点看三处——引号怎么拼、`pythonw`/解释器怎么挑、"失效"怎么判定。
