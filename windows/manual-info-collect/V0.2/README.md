# V0.2 · 幂等、解释器挑选、失效检测

> **一句话目标**：让自启"装得住、卸得掉、验得出"——重复装不出错，能挑到带 tkinter 的解释器，`status` 能判断注册表里的路径是否还有效。
>
> **状态**：✅ 核心功能已完成（2026-11-04）。本文档同时记录实现、实测结果与三处已知缺陷。

V0.1 证明了"能自启"，但它很脆：换个 Python 就废、路径一改就静默失效、`status` 只会念注册表内容而不会判断对错。V0.2 补的就是这三层。

---

## 一、成品是什么

`app.py` 约 150 行，八个函数 + 一段分发，仍然零第三方依赖。

| 函数 | 职责 | 本版新增 |
|---|---|---|
| `main()` | 被拉起后写一行日志 | —— |
| `launcher_command()` | 拼出要写进注册表的命令 | 改用 `pick_python()` |
| `install()` | 写入 `HKCU\...\Run` | —— |
| `uninstall()` | 删除该值（幂等） | —— |
| `has_tkinter(p)` | 子进程探测某解释器能否 `import tkinter` | ✅ 新 |
| `pick_python()` | 从候选里挑第一个可用的解释器 | ✅ 新 |
| `command_paths(cmd)` | 从命令串里抠出所有文件路径 | ✅ 新 |
| `status()` | 四类状态判定 | ✅ 重写 |

新增 import：`subprocess`（探测用）。**没有**引入 `os`、`functools`——自动扫描安装目录和缓存优化都还没做，见"已知缺陷"。

---

## 二、三个关键实现点

### 1. `has_tkinter()`：必须开子进程

```python
def has_tkinter(python_path: Path) -> bool:
    try:
        r = subprocess.run(
            [str(python_path), "-c", "import tkinter"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
```

五个参数的用意：

| 参数 | 作用 | 不写的后果 |
|---|---|---|
| 列表形式 `[程序, 参数]` | 每个参数独立传递 | 路径带空格会被切错 |
| `capture_output=True` | 抓走子进程输出 | 报错信息刷到主程序终端 |
| `text=True` | 直接得到 `str` | 要手动 `.decode()` |
| `timeout=5` | 最多等 5 秒 | 坏解释器会永久卡住 |
| `CREATE_NO_WINDOW` | 不分配控制台 | 每探测一次闪一下黑框 |

**为什么不能在当前进程里 `import tkinter` 试探**：试过之后 `sys.modules` 会留下状态，再判断就不准；而且"我这个进程有"不等于"另一个解释器有"。子进程跑完就退出，干净。

两个异常都必须接：`OSError`（路径不存在/不可执行/没权限）、`TimeoutExpired`（卡死）。**"这个候选不可用"不是程序错误**，返回 `False` 即可。

### 2. `pick_python()`：候选 + 短路 + 降级

```python
def pick_python() -> Path:
    candidates = [
        Path(sys.executable),
        Path(r"C:\Users\29242\AppData\Local\Programs\Python\Python314\python.exe"),
    ]
    for candidate in candidates:
        if candidate.exists() and has_tkinter(candidate):
            return candidate
    return Path(sys.executable)
```

三层设计：

| 层 | 代码 | 作用 |
|---|---|---|
| 顺序 | `candidates` 列表 | 第一个是"当前解释器"，优先信任它 |
| 短路 | `candidate.exists() and has_tkinter(...)` | `exists()` 便宜先判，不存在的直接跳过，**不会白跑一次子进程** |
| 降级 | 循环末尾 `return Path(sys.executable)` | 全都不行也要返回一个能用的，**降级不中止** |

关于"都没有 tkinter 会怎样"：仍然用当前解释器，也仍然用 `pythonw.exe`（`launcher_command` 里换的）。因为**采集不需要 tkinter，只有将来的配置界面需要**——缺它只损失一个功能，不该让整个程序起不来。

判断一个依赖该不该致命，看它是否在关键路径上。

### 3. `command_paths()`：按双引号切，不按空格

```python
def command_paths(cmd: str) -> list[str]:
    paths = []
    for part in cmd.split('"'):
        s = part.strip()
        if s.endswith('.exe') or s.endswith('.py'):
            paths.append(s)
    return paths
```

为什么必须检查 **`.exe` 和 `.py` 两个**：

```
"C:\...\Python314\pythonw.exe"  "F:\...\V0.2\app.py"  --run
└── ① 解释器：Python 升级/卸载会失效 ──┘  └── ② 脚本：项目搬家会失效 ──┘
```

- 只查 `.py` → Python 从 3.14 升到 3.15 后，脚本还在、解释器没了，`status` 依然报"已安装"，**开机必然静默失败**
- 检查成本是 `Path.exists()`（微秒级），没有理由留盲区

为什么不用按空格切、也不用 `shlex`：路径里可能有空格（`C:\Program Files\...`），按空格会切碎；`shlex` 把 `\` 当转义符，Windows 路径会切错。**按 `"` 切最稳**，因为 Windows 文件名不允许包含双引号。

> 这是针对当前命令形态的启发式规则。以后若命令里出现 `--config "…json"`，记得把后缀列表扩展成 `endswith((".exe", ".py", ".json"))`。

---

## 三、四类状态判定

```python
print(f"当前状态：{'已安装' if actual else '未安装'}")     # ① 有没有值

if actual:
    missing = []
    for p in command_paths(actual):
        if not Path(p).exists():
            missing.append(p)
    if missing:
        print("当前启动命令中存在不存在的路径：")            # ② 路径失效
        ...

if actual and actual != expected:
    print("⚠ 与当前程序位置不一致")                        # ③ 位置不符
    ...
```

| 顺序 | 判定 | 含义 | 严重程度 |
|---|---|---|---|
| 1 | 值不存在 | 没装 | —— |
| 2 | 有路径不存在 | **开机必然失败** | 最高 |
| 3 | 路径都在但不等于预期 | 能启动，但启动的是别的东西（如旧版本） | 中 |
| 4 | 其余 | 正常 | —— |

**2 和 3 是两件不同的事，不能合并**：失效是"文件没了"，不一致是"文件在，但不是这一个"。前者必须修，后者可能只是你从 V0.1 切到了 V0.2。

顺序也有讲究：**失效排在前面**，因为它必然导致启动失败；不一致只是"启动了别的版本"。

---

## 四、实测：三个场景

### 场景 1 · 正常

```powershell
py -3 V0.2\app.py --install
py -3 V0.2\app.py --status
```

```
当前状态：已安装
当前解释器：C:\Users\29242\AppData\Local\Programs\Python\Python314\python.exe
当前解释器已安装tkinter
```

### 场景 2 · 指向 V0.1（路径有效，但不是当前位置）

```powershell
py -3 V0.1\app.py --install      # 用 V0.1 的 install 改写注册表
py -3 V0.2\app.py --status
```

```
当前状态：已安装
⚠ 与当前程序位置不一致
预期启动命令： "…pythonw.exe" "F:\…\V0.2\app.py" --run
当前启动命令： "…pythonw.exe" "F:\…\V0.1\app.py" --run
当前解释器：C:\…\Python314\python.exe
当前解释器已安装tkinter
```

**注意它没有报"路径不存在"**——V0.1 的 `app.py` 是真的存在的。这正是两类判定的区别。

### 场景 3 · 路径失效

手工把注册表改坏（`reg.exe` 被本机程序黑名单拦截，改用 `winreg` 直接写）：

```python
import winreg
q = chr(34)                                   # 双引号，避免在命令行里转义地狱
val = q + r'C:\no\such\pythonw.exe' + q + ' ' + q + r'F:\...\V0.2\app.py' + q + ' --run'
with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r'Software\Microsoft\Windows\CurrentVersion\Run',
                    0, winreg.KEY_WRITE) as k:
    winreg.SetValueEx(k, 'ManualInfoCollect', 0, winreg.REG_SZ, val)
```

```
当前状态：已安装
当前启动命令中存在不存在的路径：
不存在的路径：C:\no\such\pythonw.exe
⚠ 与当前程序位置不一致
...
```

只报 `.exe` 不存在、没报 `.py`——因为脚本路径是好的。**逐个检查的意义就在这里。**

修好：`py -3 V0.2\app.py --install`。

---

## 五、真实踩过的坑

**① `--run` 又被改错了（V0.1 的坑重现）**

`launcher_command()` 的返回值一度被写成 `--install`、`--uninstall`、`--status`。这一行决定"**开机时执行什么**"，只能是干活的那个入口。写成 `--uninstall` 等于每次开机把自己卸掉。

**② `except FileExistsError` 是死代码**

`CreateKeyEx` 的语义是"存在就打开"，不会抛 `FileExistsError`（那是文件系统 `open(..., "x")` 的异常）。注册表操作失败一律是 `OSError`。写错的 `except` 不报错，只是永远不触发，制造"我处理过了"的错觉。

**③ "本来就没有"返回了 `False`**

```python
except FileNotFoundError:
    return False, "本来就没有安装，无需删除"    # ❌ 应为 True
```

CLI 只打印消息，所以看不出问题；等 V0.8 的 GUI 用 `ok` 判断时才会暴露。**返回错值比不返回更危险**，因为它看起来像处理过了。

**④ 补失效检测时，把"不一致"检测弄丢了**

加新逻辑时覆盖了原有分支，导致 `actual != expected` 不再被检查。症状：注册表指向 V0.1 时 `status` 只说"已安装"，看起来完全正常。**改 `status` 这种"输出型"函数时，最容易在重写中丢条件。**

**⑤ `command_patch` → `command_paths`**

拼写错误（patch/paths）。功能正常，但名字错了以后读代码要绕一下。改名时记得同步改调用处。

**⑥ tkinter 探测很慢，`status` 因此变慢**

实测单步耗时：

```
py -3 -c print(sys.executable)    758 ms
python -c import tkinter         1414 ms
python -c pass（纯启动）           497 ms
```

`status` 里 `launcher_command()`、`pick_python()`、`has_tkinter(python)` 各探测一次，合计约 **2.9 秒**。属于体验问题，不是功能问题，见"已知缺陷 ②"。

---

## 六、验收结果

| 验收项（README 原文） | 结果 |
|---|---|
| 连续 `install` 三次，无报错，注册表值不变 | ✅ 覆盖写，天然幂等 |
| `uninstall` 两次，第二次提示"本来就没装"且不报错 | ✅ |
| 把注册表路径改成不存在的文件，`status` 报"路径已失效" | ✅ 场景 3 |
| 把值改成能跑但不该用的路径，`status` 报"不一致" | ✅ 场景 2 |
| `status` 能显示最终选了哪个解释器、是否带 tkinter | ✅ |

---

## 七、已知缺陷（重要，不要当作已完成）

### ① 候选列表是硬编码的

```python
Path(r"C:\Users\29242\AppData\Local\Programs\Python\Python314\python.exe")
```

这条路径**只在这台机器上成立**。换台电脑、或者在别的 Windows 账户下跑，第二个候选直接失效（`exists()` 为 False 被跳过），`pick_python` 退化成"只用当前解释器"——**功能不会崩，但"自动挑解释器"这个能力等于没有**。

要做到真正自动，需要枚举来源：

| 来源 | 方法 | 额外开销 |
|---|---|---|
| `py` 启动器的默认版本 | `py -3 -c "import sys; print(sys.executable)"` | ~758 ms |
| 常见安装目录 | `%LOCALAPPDATA%\Programs\Python\Python3*`，用 `glob` 匹配 | 毫秒级 |
| 注册表 `HKLM\SOFTWARE\Python\PythonCore\*\InstallPath` | 最权威，但要读 HKLM | 毫秒级 |

这些留到后续版本，或者等到真正出现"多 Python 环境"的需求时再做。

### ② `status` 约 3 秒

原因：同一件事（探测 tkinter）做了 3 次。两种修法：

| 修法 | 改动量 | 效果 | 需要理解 |
|---|---|---|---|
| 让 `launcher_command(python=None)` 接受已选好的解释器 | 3 行 | 约 2 秒 | 默认参数 |
| `functools.lru_cache` 缓存 `has_tkinter` / `pick_python` | 2 行装饰器 | 首次 1 秒内，重复 0 ms | 装饰器 + 缓存键 |

**当前阶段功能优先，暂不处理。** 等 V0.3 加了日志之后，慢的问题会更容易定位。

### ③ 没有 `(ok, msg)` 返回值

`install`/`uninstall` 仍是 `print` 版。后果：函数既干活又输出，将来 V0.8 的 GUI 按钮复用时必须再改一遍。

这是有意的取舍——先确保每一步都能看懂，而不是一次塞进多种写法。等 V0.8 做界面时再改，那时"为什么返回值比打印好"会变得具体。

---

## 八、与正式版的差异

| 项 | V0.2 | 正式版 `autostart.py` |
|---|---|---|
| 候选来源 | 硬编码 2 个 | 当前解释器 + `py` 启动器 + `LOCALAPPDATA` 扫描，去重保序 |
| 探测开销 | 每次调用都探 | 结果缓存 |
| 返回值 | `print` | `(ok, msg)`，CLI 只负责打印 |
| 失效判定 | 路径存在性 | 路径存在性 + 值是否与当前形态一致 |
| tkinter | 只探测并显示 | 参与挑选，缺它也降级运行 |
| 失效提示 | 打印"重新 install" | 配置界面/托盘里给一键修复 |

---

## 九、完成后你应当能回答

- 为什么探测 tkinter 必须开子进程，不能在当前进程里 `import`？
- `pick_python` 里为什么先判 `exists()` 再判 `has_tkinter()`？（提示：短路求值 + 成本差异）
- 所有候选都没有 tkinter 时，程序还能不能自启？会损失什么？
- 为什么要检查 `.exe` 和 `.py` **两个**路径，只查 `.py` 会漏掉什么？
- "路径已失效"和"与当前位置不一致"分别对应什么场景？为什么不能合并？
- `CreateKeyEx` 在键已存在时会抛异常吗？为什么 `except FileExistsError` 是死代码？

---

## 十、下一步：V0.3

V0.2 之后，自启本身已经"装得上、验得出"了。但还有一类问题没解决：**程序在 `pythonw` 下崩溃时，你什么都看不到。**

V0.3 要补的是可观测性：

1. `logging` 模块 + 文件轮转（替代所有 `print`）
2. `sys.excepthook` 全局异常兜底（任何未捕获异常都写进日志，含完整 traceback）
3. 日志级别与格式，让"哪天几点发生了什么"可回溯

这正是 V0.1 里 `print(line)` 在 `pythonw` 下抛 `AttributeError` 却无人知晓的问题的正式解法。

参考文件：`windows/info-collect/win/app.py` 的 `setup_logging()` / `install_excepthook()`。
