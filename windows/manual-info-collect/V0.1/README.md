# V0.1 · 写入注册表并启动自己

> **一句话目标**：让一个 Python 脚本把自己写进注册表自启项，注销重登后能被自动拉起；拉起后往文件里追加一行时间戳。

这一版不采集任何东西，只证明一件事：**自启这条路能走通**。

---

## 前置条件

- 无。这是第一版，从空文件开始写。

---

## 只做四件事

1. `install`：往 `HKCU\...\Run` 写一个值
2. `uninstall`：把那个值删掉
3. `status`：读出来对比"应写值"和"实际值"
4. `--run`：被拉起时执行的动作（写日志）

---

## 目录与文件

```
V0.1/
├── README.md
├── app.py          ← 你写这个
└── run.log         ← 运行时自动生成，不要手动创建
```

---

## 实现步骤

### Step 1 · 常量区

先定四个常量，后面所有函数都用它们，避免路径散落各处：

| 常量 | 值 |
|---|---|
| `APP_NAME` | `"ManualInfoCollect"`（同时用作注册表值名） |
| `REG_RUN` | `r"Software\Microsoft\Windows\CurrentVersion\Run"` |
| `LOG_DIR` | `Path(os.environ["LOCALAPPDATA"]) / APP_NAME` |
| `LOG_FILE` | `LOG_DIR / "run.log"` |

用 `r"..."` 原始字符串，否则 `\Run` 里的 `\R` 会被当成转义。

### Step 2 · 被拉起后做什么：`run_main()`

写一行到日志：

```
2026-11-03 10:50:12 | argv=['F:\\...\\app.py', '--run']
```

要点：
- 先 `LOG_DIR.mkdir(parents=True, exist_ok=True)`
- 用 `open(LOG_FILE, "a", encoding="utf-8")` 追加，不要覆盖
- **把 `sys.argv` 也写进去**：这是排查"被谁、用什么参数拉起来的"最直接的线索

### Step 3 · 拼命令：`launcher_command()`

返回一个字符串，将来原样写进注册表。三件事：

1. 取 `Path(sys.executable)`，把文件名换成 `pythonw.exe`（**同目录存在才换**，否则保留原样）
2. 取 `Path(__file__).resolve()` 作为脚本绝对路径
3. 拼成 `f'"{exe}" "{script}" --run'` —— **两段路径都要加引号**

### Step 4 · 写注册表：`install()`

```
winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_SET_VALUE)
winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, cmd)
```

- 用 `with` 包住键对象，退出自动关闭句柄
- 值类型必须是 `REG_SZ`
- 返回值建议设计成 `(ok: bool, msg: str)`，方便 CLI 打印

### Step 5 · 删注册表：`uninstall()`

```
winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_SET_VALUE)
winreg.DeleteValue(key, VALUE_NAME)
```

必须单独处理 `FileNotFoundError`：值不存在、键不存在都算"本来就没装"，**这是成功而不是失败**。这个判断后面每一版都会用到。

### Step 6 · 查状态：`status()`

读回实际值，然后把两个东西**并排打印**：

```
应写命令： "C:\...\pythonw.exe" "F:\...\app.py" --run
实际命令： "C:\...\pythonw.exe" "F:\...\app.py" --run
```

两行一致 = 正常。这一步是 V0.1 里性价比最高的设计：以后所有"自启没生效"的问题，都从这两行的差异开始查。

### Step 7 · 入口分发

`sys.argv[1]` 分支：

| 参数 | 行为 |
|---|---|
| `install` | 写入，打印实际写入的字符串 |
| `uninstall` | 删除，打印结果 |
| `status` | 对比打印 |
| `--run` | 执行 `run_main()` |
| 其他/缺省 | 打印用法，返回非 0 |

注意 `--run` 用双横线：它是"被系统调用"的入口，不是给人手敲的命令，视觉上区分开。

### Step 8 · 三步验证

1. **装**：`py -3 app.py install`，然后
   `reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v ManualInfoCollect`
   应看到 `REG_SZ` 和那串命令
2. **跑**（不用真的注销）：把注册表里那串命令**整段复制到 CMD** 执行 —— 这与登录时被拉起完全等价。然后看 `run.log` 是否多一行
3. **卸**：`py -3 app.py uninstall`，再 `reg query` 应报"找不到"

真实验证一次：注销 → 重新登录 → 看日志。这一步建议做一次，确认没有"手动能跑、自启不跑"的差异。

---

## 会用到的 API

| 用途 | API |
|---|---|
| 开/建键 | `winreg.CreateKeyEx(HKEY_CURRENT_USER, sub_key, 0, KEY_SET_VALUE)` |
| 写值 | `winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)` |
| 开已存在的键 | `winreg.OpenKey(HKEY_CURRENT_USER, sub_key, 0, KEY_SET_VALUE)` |
| 读值 | `winreg.QueryValueEx(key, name)` → `(value, type)` |
| 删值 | `winreg.DeleteValue(key, name)` |
| 找 pythonw | `Path(sys.executable).with_name("pythonw.exe")` |

---

## 四个坑（都是真实踩过的）

**① `python.exe` 会带黑窗口。**
自启必须用 `pythonw.exe`（GUI 子系统，PE Subsystem = 2，不分配控制台）。用错了表现是：开机后桌面上多一个黑框，关掉它采集就停。

**② 引号只能包路径。**
`"C:\a b\app.exe" --run` 正确；`"C:\a b\app.exe --run"` 会把 `--run` 当成路径的一部分，程序找不到。Windows 把整串交给 `CreateProcess`，按空格切分。

**③ 值类型是 `REG_SZ`，不是 `REG_EXPAND_SZ`。**
后者只在你需要 `%APPDATA%` 这类变量展开时使用。选错通常不报错，但语义不对。

**④ 写进去的是绝对路径，搬家就失效，而且失败是静默的。**
V0.1 不解决，但要知道：`pythonw` 启动失败没有任何提示，日志不增就是失败。

---

## 验收标准

- [ ] `install` 后 `reg query` 能看到值，内容为 `"…pythonw.exe" "…app.py" --run`
- [ ] 执行该命令后 `run.log` 多一行，且含时间戳与 `argv`
- [ ] `uninstall` 后值消失；再次 `uninstall` 不报错（幂等）
- [ ] `status` 能并排显示应写值与实际值
- [ ] 注销重登后，`run.log` 自动多一行（不用手点任何东西）

---

## 常见卡点

| 现象 | 原因 | 处理 |
|---|---|---|
| `status` 正常但重登没反应 | 命令里的解释器路径不存在 / 用了 `python.exe` 被安全软件拦 | 手动执行那串命令，看报错 |
| `reg query` 说找不到 | 写到了 HKLM，或者值名不一致 | 检查根键与 `VALUE_NAME` |
| 日志是空的但进程"好像跑了" | 写到了别的目录（`__file__` 相对路径） | 日志路径用绝对路径，`resolve()` |
| `uninstall` 抛 `FileNotFoundError` | 没做异常处理 | 这是正常情况，按成功处理 |

---

## 完成后你应当能回答

- 为什么写 `HKCU` 不需要管理员，写 `HKLM` 需要？
- 为什么自启命令里要写 `pythonw.exe` 而不是 `python.exe`？
- 日志为什么要记录 `sys.argv`？
- 为什么"值不存在"这种删除结果要算成功？

---

## 参考文件（写完再对照）

`windows/info-collect/win/autostart.py` —— 整个自启逻辑约 220 行，核心三个函数：
`packaged_exe()` / `launcher_command()` / `install()` `uninstall()`。

对照时重点看三处差异：引号怎么拼、`pythonw` 怎么挑、"失效"怎么判定。
