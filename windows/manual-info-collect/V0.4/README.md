# V0.4 · 单实例锁（已完成）

> **一句话目标**：同一时刻只允许一个实例运行——第二次启动时提示"已经在运行"，然后退出。
>
> 状态：✅ 已完成（2026-11-04），5 条验收全部实测通过。

---

## 一、V0.3 → V0.4 只有三处变化

| 变化 | 内容 |
|---|---|
| 新增常量 | `MUTEX_NAME`、`ERROR_ALREADY_EXISTS`、模块级 `_mutex_handle = None` |
| 新增两个函数 | `acquire_single_instance()`、`alert()` |
| `main()` 改造 | 返回类型 `None` → `int`；进门第一件事先抢锁；`__main__` 用 `sys.exit(main())` 传退出码 |

上一版的另外两个 bug 也顺手修了：`status()` 全部改回 `print`（诊断命令不写日志），`install()` / `uninstall()` 补上 `logger.info`。

---

## 二、核心代码

```python
MUTEX_NAME = rf"Local\{APP_NAME}_SingleInstance"
ERROR_ALREADY_EXISTS = 183

_mutex_handle = None          # 必须挂在模块级：句柄一丢，锁就没了


def acquire_single_instance() -> bool:
    global _mutex_handle

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]

    handle = kernel32.CreateMutexW(None, 0, MUTEX_NAME)
    if not handle:
        return True                      # 建不出来就放行，别把程序卡死

    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return False

    _mutex_handle = handle
    return True
```

`main()` 里：

```python
def main() -> int:
    if not acquire_single_instance():
        logger.warning("已有实例在运行，本次启动放弃")
        alert(f"{APP_NAME} 已经在运行了。")
        return 1

    logger.info("程序开始运行了")
    return 0
```

---

## 三、三个必须懂的点

### 1. 内核对象可以带名字，名字就是锁

Windows 的 mutex / event / semaphore 都能起名，名字在整个登录会话内唯一。

- 第一个进程建 `Local\ManualInfoCollect_SingleInstance` → 系统**新建**一个，返回新句柄
- 第二个进程用**同一个名字**建 → 系统**不新建**，把已有那个的句柄还给你，同时把错误码设成 `183`

也就是说：**"这个名字存在"本身就等于"已经有人在跑"**。这就是判断依据。

比另两种土办法强的理由：

| 办法 | 缺点 |
|---|---|
| 扫进程列表 | 慢；同名进程不一定是同一个程序；别的程序也能叫这个名字 |
| 写 PID 文件 | 进程被强杀时文件留着 → 僵尸锁，下次启动以为还在跑 |
| 命名 mutex | 进程死掉时**内核自动释放**，不会留残骸 |

### 2. 句柄不能是局部变量

`_mutex_handle = handle` 这一句把句柄存到模块级。

理论上的理由是"局部变量随函数返回消失，对象被回收后锁就放了"。实际在 ctypes 里更朴素：`handle` 只是个整数，**它不会自己失效**，但如果你不存起来，就再也没法 `CloseHandle`、也没法确认自己手里还握着锁。

**结论按任务书办：`_mutex_handle` 写在模块级，函数里用 `global` 声明。** 这是"我确实持有它"的唯一凭证。

### 3. 为什么要 `use_last_error=True` + `ctypes.get_last_error()`

任务书里写的是 `ctypes.windll.kernel32` + `kernel32.GetLastError()`。**能跑，但不可靠。**

原因：`GetLastError` 返回的是"**当前线程最后一次** API 调用的错误码"。而 ctypes 在调用 Python 侧包装函数、做类型转换时，**可能又调用了别的 Win32 API**，把你的错误码覆盖掉。等你读到的时候，可能已经是 `0`。

`use_last_error=True` 让 ctypes 在调用返回的**那一瞬间**把错误码存进一个 Python 侧的安全位置，`ctypes.get_last_error()` 读的是这个副本，不受后续调用干扰。

这叫**错误码的原子捕获**。凡是"调用后必须立刻读错误码"的 Win32 API（`GetLastError`、`errno` 同理），都该这么写。

### 一个补充：`if not handle` 为什么返回 `True`

拿不到互斥体（极端情况下权限或资源问题）时，选择**放行**而不是拦截。理由是：单实例锁是"防重复"的优化，不是安全边界。为了防重复而让程序完全起不来，代价更大。

---

## 四、实测证据

四条命令跑出来的真实结果：

```
$ py -3 app.py --run
第一个实例退出码=0                      <- 抢到锁

（另一个进程持锁期间）
$ py -3 app.py --run
ManualInfoCollect 已经在运行了。
第二个实例退出码=1                      <- 被拦住

（持锁进程结束后）
$ py -3 app.py --run
锁释放后再启动，退出码=0                <- 内核自动放锁

（持锁期间）
$ py -3 app.py --status
当前状态：已安装
⚠ 与当前程序位置不一致
...
status 退出码=0                         <- 手动命令不受锁影响
```

日志文件里的对应记录：

```
2026-11-04 17:29:39 INFO     程序开始运行了
2026-11-04 17:29:46 WARNING  已有实例在运行，本次启动放弃
2026-11-04 17:30:03 INFO     程序开始运行了
```

`WARNING` 那一行就是"第二次启动被拦住"的铁证。

**关于"强杀后能否重启"**：内核对象在进程终止时无条件释放，`taskkill /F` 和正常退出没有区别。上面第 3 条（进程结束后能重新抢到锁）验的就是同一套机制。

---

## 五、坑

| 坑 | 表现 | 处理 |
|---|---|---|
| 用 `kernel32.GetLastError()` | 偶尔永远认为自己是唯一实例，锁时灵时不灵 | 用 `WinDLL(..., use_last_error=True)` + `ctypes.get_last_error()` |
| 读错误码前插了别的 API 调用 | 错误码被覆盖成 0 | `CreateMutexW` 后面紧接着读，中间什么都不做 |
| 名字在两处各写一遍 | 拼错一个字，锁就失效 | 抽成 `MUTEX_NAME` 常量 |
| 在 `--run` 之外也抢锁 | `status` / `install` 被误拦 | 只在 `main()` 里抢 |
| 弹窗写死在所有场景 | 终端调试时卡住等你点"确定" | `alert()` 里先判断 `sys.stdout is not None`，有控制台就 print |
| 复用 `Global\` 前缀 | 多用户/远程登录时互相干扰 | 个人程序统一 `Local\` |

**最后两条里，第二个是我这次真实撞到的**：一开始想直接 `MessageBoxW`，结果自动化测试会被弹窗卡死。改成"有控制台就打印、没有才弹窗"之后才测得下去。这也顺带解释了 `alert()` 里那个分支的意义。

---

## 六、验收清单

- [x] 启动第一个实例，正常运行
- [x] 再启动第二个，立即提示并退出，退出码 1
- [x] 日志里能看到"已有实例在运行"的 WARNING
- [x] 第一个实例结束后，可以正常启动新实例（锁自动释放）
- [x] `status` / `install` 不受锁影响

---

## 七、V0.5 要解决的问题

现在程序跑起来后**没有任何界面**：用户不知道它在哪、也不能让它退出，只能去任务管理器杀进程。

V0.5 加托盘图标：`Shell_NotifyIconW` + 隐藏窗口 + 消息循环 + 右键菜单（退出/打开日志/状态）。这一版会第一次接触 ctypes 的**结构体**和 Windows 的消息机制。

---

## 参考文件

`windows/info-collect/win/app.py` 的 `acquire_single_instance()`。正式版还多做了一件事：抢锁失败时 `CloseHandle` 掉拿到的那个句柄（我们这版直接返回，靠进程退出时系统回收——反正它马上就退了）。
