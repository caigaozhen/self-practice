# V0.2 · 幂等、解释器挑选、失效检测

> **一句话目标**：让自启"装得住、卸得掉、验得出"——重复装不出错，能自动挑到合适的解释器，`status` 能判断注册表里的路径是否还有效。

V0.1 证明了"能自启"，但它很脆：换个 Python 就废、路径一改就静默失效、`status` 只会念注册表内容而不会判断对错。

---

## 前置条件

V0.1 已完成并通过验收：能 install / uninstall / status / --run，重登后日志有记录。

---

## 要做四件事

### 1. 幂等

`install` 连续执行三次不应报错；`uninstall` 在"本来就没有"时也应返回成功。

- 写值：`SetValueEx` 本身是覆盖语义，天然幂等，不需要先删再写
- 删值：`DeleteValue` 抛 `FileNotFoundError` 时按成功处理
- 返回值统一成 `(ok: bool, message: str)`，让 CLI 只负责打印

### 2. 自动挑解释器

不能无脑用 `sys.executable`：当前进程可能就是"没有 tkinter 的那个"（比如某些嵌入式发行版或精简环境），而 V0.8 要做 tkinter 配置界面。

候选顺序：

1. `sys.executable`
2. `py -3 -c "import sys; print(sys.executable)"` 的输出
3. `%LOCALAPPDATA%\Programs\Python\Python3*\python.exe`（按版本倒序）
4. 全都不可用时退回 `sys.executable`，并在 `status` 里标出"缺 tkinter"

**探测方法**：开子进程跑 `python -c "import tkinter"`，返回码 0 即可用。

> 为什么不能在当前进程里 `import tkinter` 试探：当前进程如果是从 `pythonw` 起的、或者已经 import 失败过一次，`sys.modules` 里会留下状态，试不准。子进程是干净的。

### 3. `status` 做失效检测

把命令字符串里的路径抠出来（按引号切分，取以 `.exe` / `.py` 结尾的段），逐个 `Path(p).exists()`：

| 判定 | 含义 | 打印 |
|---|---|---|
| 值不存在 | 没装 | `未启用` |
| 路径全部存在且等于应写值 | 正常 | `已启用` |
| 有路径不存在 | **失效**（搬过家 / Python 被卸载） | `⚠ 路径已失效` |
| 路径都在但与应写值不同 | 指向旧位置 | `⚠ 与当前程序位置不一致` |

这三类判定是后面所有"自启不生效"排查的基础，务必分清。

### 4. 提示"取消再勾选可修复"

配置界面（V0.8）和托盘（V0.5）都会用到这句话：**先 `uninstall` 再 `install`** 就能重写。V0.2 阶段先让 CLI 打印出来。

---

## 关键 API

```python
subprocess.run([python, "-c", "import tkinter"], capture_output=True, timeout=10)
subprocess.run(["py", "-3", "-c", "import sys; print(sys.executable)"],
               capture_output=True, text=True)
```

- Windows 上开子进程建议加 `creationflags=subprocess.CREATE_NO_WINDOW`，否则会闪黑框
- 每个探测都要 `timeout`，坏掉的解释器会卡住

---

## 实现步骤

1. 把 V0.1 的 `install/uninstall` 改成返回 `(ok, msg)`，CLI 只打印
2. 加 `candidate_interpreters()` → 去重后的候选列表
3. 加 `has_tkinter(python)` → 子进程探测
4. 加 `pick_interpreter()` → 返回 `(pythonw路径, 是否带tkinter)`
5. 改 `launcher_command()` 用它
6. 加 `diagnose()` → 返回 `enabled / command / expected / stale / missing_tk` 五个字段
7. `status` 基于 `diagnose()` 打印

---

## 坑

| 坑 | 说明 |
|---|---|
| `py` 启动器不存在 | 精简安装或非官方发行版可能没有，要 `try/except` 跳过 |
| 探测超时 | 用 `timeout=10`，并捕获 `subprocess.TimeoutExpired` |
| 路径解析漏掉空格 | 命令是 `"a b.exe" "c d.py" --run`，按引号切而不是按空格切 |
| 把"缺 tkinter"当致命错误 | 采集不需要 tkinter，只是配置窗打不开，应降级而不是中止 |

---

## 验收标准

- [ ] 连续执行 `install` 三次，无报错，注册表值不变
- [ ] `uninstall` 两次，第二次不报错且提示"本来就没装"
- [ ] 把注册表里的路径手工改成不存在的文件，`status` 报"路径已失效"
- [ ] 把值改成一个能跑但不该用的路径，`status` 报"与当前位置不一致"
- [ ] `status` 能显示最终选了哪个解释器、是否带 tkinter

---

## 完成后你应当能回答

- 为什么"删除不存在的值"要算成功？
- 为什么解释器探测必须开子进程？
- "路径已失效"和"指向旧位置"这两种异常，处理方式有什么不同？

---

## 参考文件

`windows/info-collect/win/autostart.py`：
`candidate_interpreters()` / `has_tkinter()` / `pick_interpreter()` / `diagnose()`。
