# V0.2 · 采集电脑硬件数据

> 界面结构和 V0.1 相同，但标签里的文字改成**运行时现场采集**的本机硬件信息，并加了一个「刷新」按钮。

**状态**：✅ 已完成（2026-11-05），源码可运行，`HardwareInfo.exe` 已打包验证（`--selftest` 退出码 0）。

---

## 一、V0.1 → V0.2

| 项 | V0.1 | V0.2 |
|---|---|---|
| 数据来源 | 写死的两个字典 | 四个采集函数，现场读取 |
| 界面控件 | Label | Label + Button |
| 依赖 | 无 | `platform`/`winreg`/`time` + **`psutil`** |
| 入口结构 | 代码平铺 | GUI 放进 `if __name__ == "__main__":` |
| exe 名 | `TkDemo.exe` | `HardwareInfo.exe` |

```bash
py -3 -m pip install -r requirements.txt   # 只有开发时需要；exe 里已内置 psutil
```

---

## 二、采了什么，从哪来

| 显示项 | 来源 |
|---|---|
| 计算机名 / 系统 / 版本 / 架构 | `platform.node()` / `system()` / `version()` / `machine()` |
| 开机时间 | `psutil.boot_time()` 格式化 |
| CPU 型号 | 注册表 `CentralProcessor\0` 的 `ProcessorNameString` |
| 物理 / 逻辑核心 | `psutil.cpu_count(logical=False / True)` |
| 当前频率 | `psutil.cpu_freq()` |
| CPU 使用率 | `psutil.cpu_percent(interval=0.2)` |
| 内存 总/可/占用 | `psutil.virtual_memory()` |
| 各盘 总/可/已用% | `psutil.disk_partitions()` + `disk_usage()` |

实测输出（19 行，分四块）：

```
计算机   : qishengcgz
操作系统 : Windows 11
系统版本 : 10.0.26200
架构     : AMD64
开机时间 : 2026-11-05 08:24:02

CPU 型号 : AMD Ryzen 7 PRO 6850HS with Radeon Graphics
核心数量 : 8 物理 / 16 逻辑
当前频率 : 3201 MHz
CPU 使用 : 4.5%

内存总量 : 15.3 GB      内存可用 : 3.0 GB      内存占用 : 80.2%

C:\  总   152.8 GB   可用    32.5 GB   已用  78.7%
D:\  总   400.0 GB   可用   288.4 GB   已用  27.9%
E:\  总   302.3 GB   可用   273.9 GB   已用   9.4%
F:\  总    97.7 GB   可用    96.2 GB   已用   1.5%
```

---

## 三、为什么用 psutil 而不是 ctypes

| 指标 | ctypes 版 | psutil 版 |
|---|---|---|
| 内存 | 30 行（结构体 + `GlobalMemoryStatusEx`） | 3 行 |
| 磁盘 | 15 行（`GetDiskFreeSpaceExW`） | 8 行 |
| 物理核心数 | 要解析 `GetLogicalProcessorInformation` | `cpu_count(logical=False)` |
| CPU 使用率 | 两次采样求差 | `cpu_percent(interval=0.2)` |

判断标准：**有现成库就用库**（psutil / pyserial / pywin32）；库里没有的冷门 API 才用 ctypes；只是读硬件信息，别碰 ctypes。

ctypes 仍有价值——比如 V0.4 的单实例锁 `CreateMutexW`，没有任何库封装它。

---

## 四、四个必须记住的坑

### 1. `boot_time()` 返回「时间点」，不是「时长」

```python
boot = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(psutil.boot_time()))
```

三步链：时间戳（float）→ `struct_time`（结构体）→ 字符串。

| 占位符 | 含义 | 占位符 | 含义 |
|---|---|---|---|
| `%Y` | 四位年 | `%H` | 24 小时制 |
| `%m` | 两位月 | `%M` | 分 |
| `%d` | 两位日 | `%S` | 秒 |

- `localtime` 按本机时区，`gmtime` 是 UTC（差 8 小时）
- `strftime` 参数顺序是「格式在前、时间在后」，反了 `TypeError`
- 必须格式化：`struct_time` 直接塞进 f-string 会打印成 `time.struct_time(tm_year=2026, ...)`
- Java 是 `yyyy-MM-dd HH:mm:ss`，规则不同，不能照抄

要「已运行多久」自己减（psutil 没有 `uptime()`）：

```python
sec = int(time.time() - psutil.boot_time())   # 本机 25513.5 秒 ≈ 7.1 小时
hours, remain = divmod(sec, 3600)
minutes, _ = divmod(remain, 60)
```

### 2. `cpu_count(logical=False)` 的 `logical` 是参数名

```
cpu_count()              → 16   默认等于 logical=True
cpu_count(logical=True)  → 16   逻辑核心（OS 能调度的线程数）
cpu_count(logical=False) → 8    物理核心（芯片上真实的核）
```

8/16 = 开了超线程。`or 0` 是兜底：极少数环境返回 `None`，`x or 0` 让 `None`、假值都变 0（Java 要 `Objects.requireNonNullElse`）。Python 布尔值首字母大写 `True`/`False`。

### 3. ⚠️ `cpu_freq()` 在 Windows 上不是实时频率

```
cpu_freq() -> scpufreq(current=3201.0, min=0.0, max=3201.0)
连读 5 次：3201.0 / 3201.0 / 3201.0 / 3201.0 / 3201.0
```

一动不动，`min=0`、`current == max`。因为 Windows 上 psutil 读的是注册表 `~MHz`——**标称基础频率**，不是此刻跑多少。要实时值得走 WMI（`Win32_Processor.CurrentClockSpeed`）。

`if freq else "读取失败"` 是条件表达式（`A if 条件 else B`，条件在中间，和 Java `? :` 顺序相反），防 `None` 炸 `AttributeError`。

### 4. 格式规格速查（冒号后面）

| 写法 | 效果 | 例子 |
|---|---|---|
| `:.0f` | 0 位小数、定点 | `3201.0` → `3201` |
| `:<4` | 最小宽度 4、左对齐 | `"C:"` → `"C:  "` |
| `7.1f` | 宽度 7、1 位小数 | `1863.0` → `" 1863.0"` |
| `>,` | 右对齐 + 千分位 | `1234567.9` → `1,234,567.9` |

- **宽度是「最小」不是「最多」**：`f"{'VeryLong':<4}"` → `"VeryLong"`，超长不截断，只会撑破对齐
- **宽度算总占位**（含小数点、负号）：`7.1f` = 5 位整数 + `.` + 1 位小数，最多 `99999.9`
- **`:.0f` 不是四舍五入**，是银行家舍入：`2160.5→2160`、`2161.5→2162`、`2.5→2`、`3.5→4`。和 Java `Math.round()` 不同
- `:d` 只能配整数，`f"{3201.0:d}"` 会 `ValueError`
- 必须配等宽字体 `Consolas`，空格补齐才真正对齐

---

## 五、代码结构上的两个决定

**两层 join 拼整页**（内层拼行、外层拼段）：

```python
return "\n\n".join("\n".join(block) for block in blocks)
```

`\n` 换行紧贴，`\n\n` 空一行——四块（系统/CPU/内存/磁盘）靠空行分组。`for` 外面不加方括号是**生成器**（不建临时 list），`join` 接受任何可迭代对象。不能摊平成一维再 join，那样组间边界就没了。

**GUI 包进 `if __name__ == "__main__":`**：

| 运行方式 | `__name__` | 窗口出现 |
|---|---|---|
| `py app.py` | `"__main__"` | 是 |
| `import app` | `"app"` | 否 |

所以 `py -3 -c "import app; print(app.collect_all())"` 能只取数据不弹窗。否则 `import` 会卡死在 `mainloop()`。

界面两个概念别混：

- `root.title("电脑硬件信息")` → **标题栏**；`text="正在采集…"` → 内容区的占位文字，被 `refresh()` 立刻替换
- `label.config(text=...)` 改已建控件的属性；等价 `label.configure(...)`、`label["text"] = ...`。重建 Label 会多出第二个控件、还要重 pack、界面闪一下

---

## 六、`pack()` 的规律（实测）

**先分地，再盖房**：

| 参数 | 管什么 |
|---|---|
| `expand` | 这块**地会不会变大**（抢不抢富余空间） |
| `fill` | 控件**盖不盖满这块地**（不是盖满窗口！） |

分配公式：

```
① 每个控件先拿走自然高度（winfo_reqheight）
② 窗口高 - 自然高度合计 = 富余
③ 富余平均分给所有 expand=True 的控件
④ 实际高 = 自然高 + 分到的富余额
```

本机实测（两行**都**写 `fill="both", expand=True`）：

| 场景 | label 自然高 | 富余 | 各分 | label / button 实际高 |
|---|---|---|---|---|
| 只放一个字符 `'A'` | 24 | 410 | 205 | 229 / 235（像对半分） |
| 真实 19 行文本 | 348 | **86** | **43** | **391 / 73**（明显上大下小） |

同样代码结果差 3 倍，唯一变量是内容自然高——**说明靠 `expand` 做「精确一半」不可靠**。

推荐写法（富余全给 label，按钮固定）：

```python
label.pack(fill="both", expand=True, padx=12, pady=12)
button.pack(pady=(0, 12))
```

给按钮加 `fill="both"` 的副作用：高度被拉长；**横向也被撑满**（实测 640 宽 > label 的 616），`width=12` 失效。想让按钮胖，用 `ipadx`/`ipady`（i = internal），不是 `expand`。

其他：窗口 500→700 高时，多出的 200 全给 label，button 始终贴底。调布局时给控件加 `bg="white"` 就能看清边界。`pack` 与 `grid` 同一父容器不能混用。

---

## 七、运行 / 打包 / 自检

```bash
py -3 app.py                 # 运行
py -3 app.py --selftest      # 1.2 秒后自动关窗（验证用）
双击 build.bat               # → dist/HardwareInfo.exe（约 14MB）
```

`--selftest` 的原理：

```python
if "--selftest" in sys.argv:        # sys.argv 例：['-c', 'a', 'b', '--selftest']
    root.after(1200, root.destroy)  # 非阻塞定时器，单位毫秒
```

- `root.destroy` **不能带括号**，否则立刻执行、定时器什么也没登记（同 `command=refresh`）
- 为什么要它：`--noconsole` 会**吞掉启动报错**，双击闪退看不到原因。用 `HardwareInfo.exe --selftest` + `echo %ERRORLEVEL%` 判断（0 = 正常）
- `build.bat` 必须 CRLF 换行，LF 会报 `'f' 不是内部或外部命令`

---

## 八、已知限制 & 下一版

| 限制 | 原因 | 计划 |
|---|---|---|
| 数字不会自己变 | 只有手动刷新 | V0.3 |
| 每次刷新卡 0.2 秒 | `cpu_percent(interval=0.2)` 阻塞 | V0.3 改 `None` |
| 频率是标称值 | Windows 读注册表 | 要 WMI，暂不做 |
| 无显卡 / 主板型号 | psutil 不提供 | 按需 |
| 文本不能选中复制 | `Label` 不支持 | 可换 `Text` |

**V0.3 目标**：`root.after()` 递归实现每秒自动刷新。

1. 拆静态信息（只采一次）与动态信息（每秒更新）
2. `cpu_percent(interval=None)` 非阻塞，**首次返回 0.0 必须丢弃**
3. 加暂停/继续（`after_cancel`）和一行状态栏（顺便练三层 `pack`）

`after()` 不是 `sleep`，是「登记一个稍后执行的回调」然后立刻返回，所以不卡界面——这是 V0.3 的核心。
