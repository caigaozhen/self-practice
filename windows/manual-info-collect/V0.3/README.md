# V0.3 · 日志与全局异常兜底

> **一句话目标**：程序在**没有任何控制台**的情况下，仍然能把"我刚做了什么、哪里炸了"完整记录下来。

自启用的是 `pythonw.exe`：没有控制台，`sys.stdout` 是 `None`。此时一个未捕获的异常，会带着全部信息一起消失——进程"醒了又没了"，你什么都看不到。

**无控制台的程序，没有日志等于瞎。**

---

## 前置条件

V0.2 完成：能装、能卸、能判定失效。

---

## 要做四件事

### 1. 文件日志（带轮转）

用标准库 `logging`：

| 项 | 取值 |
|---|---|
| 文件 | `%LOCALAPPDATA%\ManualInfoCollect\infocollect.log` |
| 格式 | `2026-11-03 10:50:12 INFO     采样启动：间隔 5s` |
| 级别 | 默认 `INFO`，加 `-v` 时 `DEBUG` |
| 轮转 | 单文件 2MB，保留 3 份（`RotatingFileHandler`） |

轮转的意义：常驻程序一跑几个月，不轮转日志会涨到几百 MB。

### 2. 同时写控制台（仅当存在）

```python
if sys.stdout is not None:
    handlers.append(logging.StreamHandler())
```

`pythonw` 下 `sys.stdout is None`，直接加 `StreamHandler` 会抛异常。这是 windowed 程序最常见的启动崩溃点。

### 3. `sys.excepthook`：兜住未捕获异常

默认行为是"打印到 stderr 然后退出"——在无控制台环境下等于什么都没发生。替换成：

```
记录完整 traceback（log.exception）
→ 如果是交互场景，弹 MessageBoxW 提示"日志在哪"
→ 正常退出
```

Python 3.8+ 还要处理线程里的异常：`threading.excepthook`。采样线程将来跑在后台线程，那个线程炸了主线程是不知道的。

### 4. 关键路径都留痕

至少要记录：程序启动（含 argv、版本）、自启状态、每次 install/uninstall、退出原因。

排查时的第一句话永远是"先看日志最后 10 行"。

---

## 关键 API

| 用途 | API |
|---|---|
| 轮转日志 | `logging.handlers.RotatingFileHandler(path, maxBytes=2*1024*1024, backupCount=3, encoding="utf-8")` |
| 未捕获异常 | `sys.excepthook = my_hook` |
| 线程异常 | `threading.excepthook = my_thread_hook`（3.8+） |
| 弹窗 | `ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)` |

`MessageBoxW` 第四个参数：`0x10` = 错误图标，`0x40` = 信息图标。

---

## 实现步骤

1. 写 `setup_logging(verbose: bool) -> Logger`
2. 在 `--run` 入口最前面调用它（**早于任何可能抛异常的代码**）
3. 写 `install_excepthook()`，在其中 `log.exception(...)`
4. 给每个 CLI 分支加首尾日志
5. 自测：在 `run_main()` 里故意 `1/0`，看日志里有没有完整 traceback

---

## 坑

| 坑 | 说明 |
|---|---|
| `sys.stdout` 为 `None` | `print()` 直接抛 `AttributeError`；要用 `log`，或先判空 |
| 日志目录不存在 | `mkdir(parents=True, exist_ok=True)`，且要在建 handler 之前 |
| 编码 | Windows 默认 GBK，中文日志要显式 `encoding="utf-8"`，否则乱码 |
| 异常发生在日志初始化之前 | 初始化代码本身要 `try/except` 兜住 |
| 只在 `except` 里 `log.error(str(e))` | 丢栈。用 `log.exception()` 或 `exc_info=True` |

---

## 验收标准

- [ ] `pythonw app.py --run` 启动后，日志文件出现"启动"记录（无控制台也能写）
- [ ] 故意制造 `1/0`，日志里有 `Traceback` 和完整调用栈
- [ ] 后台线程里制造异常，日志里同样有记录
- [ ] 日志超过 2MB 时自动出现 `.1` `.2` 备份文件
- [ ] `python app.py --run`（有控制台）时，日志与控制台同时有输出

---

## 完成后你应当能回答

- 为什么 `pythonw` 下 `print()` 会出错？
- `log.error(str(e))` 和 `log.exception()` 差在哪？
- 为什么异常钩子本身也要防异常？

---

## 参考文件

`windows/info-collect/win/app.py`：`setup_logging()`、`install_excepthook()`、`setup_console()`。
