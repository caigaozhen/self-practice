# V0.3 · 日志与全局异常兜底

> **一句话目标**：程序在没有任何控制台的情况下，仍然能把“我干了什么、哪里炸了”完整记录下来。

V0.2 结束时，程序能装、能卸、能判定失效。但它有一个致命盲区：

```python
def main():
    line = f"..."
    with open(LOG_FILE, "a", encoding="utf-8") as file:
        file.write(line + "\n")
    print(line)          # pythonw 下 sys.stdout 是 None -> 抛 AttributeError
```

自启走的是 `pythonw.exe`，没有控制台。`print` 会直接崩；而且就算不崩，一个未捕获异常也**从不会经过这段代码**——它走的是 `sys.excepthook`，跟日志是两条独立通道。

**无控制台的程序，没有日志等于瞎。**

---

## 一、这一版加了什么

| 项 | V0.2 | V0.3 |
|---|---|---|
| 日志方式 | 手写 `open` / `write` / `close` | loguru 接收器 |
| 日志位置 | 脚本旁边的 `run.log` | `%LOCALAPPDATA%\ManualInfoCollect\manual-info-collect.log` |
| 编码 | 手动 `encoding="utf-8"` | 配置项 `encoding="utf-8"` |
| 轮转 | 无，会无限增长 | 10MB 切分，保留 3 份 |
| 控制台输出 | `print`（pythonw 下抛异常） | 条件性接收器，无控制台自动跳过 |
| 崩溃记录 | 无 | `sys.excepthook` 写完整 traceback |
| 输入校验 | 无 | 日志目录 `mkdir(exist_ok=True)` |
| 外部依赖 | 纯标准库 | `loguru`（`requirements.txt`） |

---

## 二、代码结构

`app.py` 按“依赖自底向上”排列，分六节：

| 区段 | 内容 | 为什么在这一层 |
|---|---|---|
| 常量 | `REG_RUN`、`APP_NAME`、`LOG_DIR`、`LOG_FILE` | 全局只读，最先需要 |
| 日志 | `mkdir` + `logger.add` | 必须在任何日志调用之前完成 |
| 异常兜底 | `handle_exception` + `install_excepthook` | 依赖 logger，所以排在日志后面 |
| 解释器探测 | `has_tkinter` → `pick_python` | 被下一节调用 |
| 注册表 | `command_paths` → `launcher_command` → `install` / `uninstall` / `status` | 依赖上面两节 |
| 业务入口 | `main` | 最后是主流程 |

**函数顺序原则**：被调用的在前，调用的在后。这样从上往下读，每个函数用到的东西都已经出现过。

---

## 三、三个关键实现

### 1. 接收器模型：一条日志，多个目的地

`logger` 是一个全局单例，内部维护一个**接收器（sink）列表**。每次 `logger.add()` 就往列表里加一个；每条日志会被复制一份发给列表里的每一个。

```python
logger.add(LOG_FILE, ...)      # 目的地一：文件
if sys.stderr is not None:
    logger.add(sys.stderr, ...)  # 目的地二：屏幕（有才加）
```

参数分两类：

| 参数 | 通用 | 只对文件有意义 |
|---|---|---|
| `sink`（第一个位置参数） | ✓ | |
| `level` | ✓ | |
| `format` | ✓ | |
| `encoding` | | ✓ 字节流才需要指定编码 |
| `rotation` | | ✓ 屏幕不会“涨到 10MB” |
| `retention` | | ✓ 屏幕不保留历史 |

### 2. 为什么换成 loguru

标准库 `logging` 要达到同样效果，需要拼四层对象：

```python
logger = logging.getLogger("app")
logger.setLevel(logging.INFO)

fmt = logging.Formatter("{asctime} {levelname:<8} {message}", style="{")
fh = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
fh.setFormatter(fmt)
logger.addHandler(fh)

sh = logging.StreamHandler()
sh.setFormatter(fmt)
logger.addHandler(sh)
```

loguru 只要一个 `add()`：

```python
logger.add(LOG_FILE, encoding="utf-8", level="INFO",
           rotation="10 MB", retention=3, format="...")
```

**代价**：多了第三方依赖；以后看别人代码里的 `getLogger` / `addHandler` 会觉得陌生（那是另一套模型，对应关系是 `add()` ↔ `addHandler()`、`level=` ↔ `setLevel()`、`format=` ↔ `Formatter`）。

### 3. `sys.excepthook`：崩溃前的最后一通电话

Python 在因未捕获异常退出前，会调用 `sys.excepthook(type, value, traceback)`。默认实现只做一件事：把 traceback 打到 `sys.stderr`——`pythonw` 下等于扔进虚空。

```python
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)   # 人为中断交回默认
        return
    logger.opt(exception=(exc_type, exc_value, exc_traceback)).error("未捕获异常，程序即将退出")


def install_excepthook():
    sys.excepthook = handle_exception      # 注意：没有括号，交出的是函数本身
```

三个参数：

| 参数 | 装的是 | `1/0` 时 |
|---|---|---|
| `exc_type` | 异常的**类** | `ZeroDivisionError` |
| `exc_value` | 异常的**实例** | `ZeroDivisionError('division by zero')` |
| `exc_traceback` | 栈帧对象，调用链的载体 | `<traceback object>` |

`logger.opt(exception=...)` 是 loguru 附带堆栈的方式，等价于 SLF4J 的 `log.error("msg", throwable)`。只写 `logger.error(str(exc_value))` 会丢栈，日志里只剩 `division by zero` 六个字，不知道崩在哪一行。

---

## 四、实测：三种启动方式的差别

| 启动方式 | `sys.stdout` / `sys.stderr` | 屏幕 | 日志文件 |
|---|---|---|---|
| `py -3 app.py --run` | 正常的流对象 | 有输出 | 有记录 |
| 在终端里调 `pythonw.exe` | **继承了终端的句柄，不是 None** | 有输出 | 有记录 |
| `start "" pythonw.exe app.py --run` | `None` | **无输出** | **有记录** |

第二行是个**测试陷阱**：在终端里手动启动 `pythonw`，标准流被继承，`sys.stderr is not None` 成立，看起来“无控制台也能打印”——其实根本不是无控制台环境。

真正的无控制台只能用 `start`（或双击、或注册表自启）来复现。实测数据：

```
启动前行数: 9
启动后行数: 10
最后一条: 2026-11-04 16:59:26 INFO     程序开始运行了
```

终端一个字没有，文件多一行——这才是自启时的真实状态。

---

## 五、踩过的坑

| 坑 | 现象 | 原因 |
|---|---|---|
| `logger.add(None)` | `TypeError: Cannot log to objects of type 'NoneType'` | 接收器不能是 `None`，所以必须先 `if sys.stderr is not None` |
| 崩溃点后面写 `logger.error` | 日志里没有这一条 | 未捕获异常会中断控制流，后面的语句不执行 |
| `logger.info("前缀：", 变量)` | 变量被吞掉，只剩前缀 | loguru 用 `{}` 占位符，没有占位符时多余参数静默丢弃 |
| 目录不存在 | `FileNotFoundError` | `open` / `logger.add` 只建文件不建目录，`mkdir` 必须在前面 |
| 不 `remove` 又 `add(sys.stderr)` | 一条日志打两遍 | 默认接收器和自定义接收器指向同一个流 |
| 终端里调 `pythonw` 测无控制台 | 屏幕上居然有输出 | 标准流被继承，不是真的无控制台 |

---

## 六、验收清单

- [x] `py -3 app.py --run`：屏幕（默认格式）和文件（自定义格式）同时有记录
- [x] `start` 脱离终端启动 `pythonw`：文件有新记录，屏幕无输出
- [x] 模拟崩溃：日志里有 `ERROR 未捕获异常` 加完整 traceback
- [x] `--status`：能报出“与当前程序位置不一致”
- [x] `--install` / `--uninstall`：日志里留下操作记录
- [ ] 轮转：单文件超过 10MB 生成备份，且只保留 3 份（需长时间运行，或临时把阈值调成 `2 KB` 验证）
- [ ] 重新 `--install` 后重启电脑，验证自启 + 日志同时工作

---

## 七、已知限制

1. **只兜主线程**。`sys.excepthook` 管不到子线程，需要 `threading.excepthook`。V0.6 有采集线程时再加。
2. **崩溃时没有界面提示**。日志写了，但用户不知道。等 V0.5 有托盘后可以加气泡提示。
3. **依赖 loguru**。换电脑要先 `pip install -r requirements.txt`，否则 `ModuleNotFoundError`。最终解法是 V0.8 打包成 exe 冻结依赖。
4. **屏幕和文件格式不一致**。屏幕用 loguru 默认格式（带毫秒和行号，级别 DEBUG），文件用自定义格式（级别 INFO）。`logger.debug` 只在屏幕出现。

---

## 八、和正式版的差异

| | 学习版（本目录） | 正式版 `windows/info-collect/win/app.py` |
|---|---|---|
| 日志库 | loguru | 标准库 `logging` + `setup_logging()` |
| 依赖 | 需要 pip 安装 | 零第三方依赖 |
| 初始化 | 模块级直接配置 | 函数封装，早于业务调用 |
| 原因 | 代码短、易读，适合学习 | 分发时不想带依赖，且部分环境无法 pip |

两者的功能等价，差别只在“愿不愿意引入第三方库”。

---

## 九、自测题

1. `pythonw` 启动时，`print("hi")` 会发生什么？为什么？
2. 为什么 `LOG_DIR.mkdir()` 必须写在 `logger.add()` 之前？
3. `logger.add(None)` 抛什么异常？为什么代码里要先判 `sys.stderr is not None`？
4. `1 / 0` 之后那行 `logger.error(...)` 为什么不会执行？要兜住它应该怎么做？
5. `logger.info("预期命令：", cmd)` 和 `logger.info("预期命令：{}", cmd)` 输出有什么不同？
6. 不 `remove` 默认接收器，又 `add(sys.stderr)`，会出现什么现象？
7. `sys.excepthook = handle` 和 `sys.excepthook = handle()` 的区别是什么？

---

## 十、下一步：V0.4 单实例锁

现在的问题：开机自启拉起一个进程，用户又双击一次，就有**两个进程同时在跑**。到了 V0.6 开始采集时，同一段时间会被记两遍。

V0.4 用 `CreateMutexW` 建一个命名互斥体，第二次启动发现自己不是唯一的，就主动退出——并且要**在日志里留下“被拦下”的记录**，否则你只会看到“双击没反应”。

---

## 参考文件

正式版：`windows/info-collect/win/app.py` 的 `setup_logging()`、`install_excepthook()`。

本目录：`app.py`、`probe_excepthook.py`（异常钩子的探针）、`requirements.txt`（在仓库根目录）。
