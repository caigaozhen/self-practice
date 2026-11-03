# V0.6 · 采集前台窗口与空闲状态

> **一句话目标**：每 5 秒采样一次，得到「当前是哪个程序、窗口标题是什么、用户是否离开」，并写进日志。

从这一版开始，程序产生**真正的数据**。但还只是"打印出来"，存储放到 V0.7。

---

## 前置条件

V0.5 完成：托盘常驻、能正常退出（否则采集起来没法停）。

---

## 四个 API，一条链路

### 1. 当前前台窗口

```python
hwnd = user32.GetForegroundWindow()      # 可能返回 0（锁屏、桌面切换瞬间）
```

### 2. 窗口属于哪个进程

```python
pid = wintypes.DWORD()
user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
```

### 3. 进程的完整路径 → 进程名

```python
h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
# PROCESS_QUERY_LIMITED_INFORMATION = 0x1000，比 PROCESS_QUERY_INFORMATION 权限要求低
buf = ctypes.create_unicode_buffer(1024)
size = wintypes.DWORD(1024)
kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
exe_name = Path(buf.value).name       # 只留文件名，如 pycharm64.exe
kernel32.CloseHandle(h)
```

`OpenProcess` 可能失败（系统进程、权限不足），必须判空句柄并跳过，不能崩。

### 4. 用户是否离开

```python
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

lii = LASTINPUTINFO()
lii.cbSize = ctypes.sizeof(LASTINPUTINFO)      # ← 不赋值，GetLastInputInfo 直接失败
user32.GetLastInputInfo(ctypes.byref(lii))
idle_seconds = (kernel32.GetTickCount64() - lii.dwTime) / 1000
```

要点：

- `cbSize` **必须先赋值**，这是 Win32 结构体的通用约定（版本兼容）
- `dwTime` 是 32 位毫秒计数，约 49.7 天回绕一次；所以要用 64 位的 `GetTickCount64()` 去减，并处理回绕
- 这个时间是**全系统**最后一次键鼠输入，不是本窗口的——所以用户在别的程序里操作，不会被误判为离开

### 5. 窗口标题（可选）

```python
user32.GetWindowTextW(hwnd, buf, 512)
```

标题可能为空（某些游戏、UWP），要能容忍。

---

## 一个必须处理的特殊情况：UWP

Windows 10/11 的计算器、设置、照片等应用，前台窗口属于 `ApplicationFrameHost.exe`，真实进程在它的子窗口里。

不做处理的表现：所有 UWP 应用都被记成同一个 `ApplicationFrameHost.exe`，报表里完全分不清。

处理思路：若进程名是 `ApplicationFrameHost.exe`，则用 `EnumChildWindows` 遍历子窗口，找到类名以 `Windows.UI.Core.CoreWindow` 或 `ApplicationFrameInputSinkWindow` 的那个，再对子窗口重新走一遍"取 PID"。

V0.6 可以先不做，但要知道**数据会不准**，并在代码里留 `TODO`。

---

## 实现步骤

1. 把所有 user32 / kernel32 的调用声明 `argtypes` 与 `restype`（64 位必须）
2. 写 `foreground_info() -> dict`，返回 `{hwnd, pid, app, title}`
3. 写 `idle_seconds() -> float`
4. 起一个后台线程，循环 `time.sleep(5)` 采样，写一行日志
5. 主线程继续跑托盘消息循环（V0.5 的）
6. 加"暂停/恢复"开关（托盘菜单里一项），验证线程可控

> 为什么采样放后台线程：托盘的消息循环必须占住主线程，采样是死循环，两者只能分线程。这也是 V0.7 要给 SQLite 加锁的原因。

---

## 坑

| 坑 | 表现 | 处理 |
|---|---|---|
| `GetForegroundWindow` 返回 0 | 锁屏/切换瞬间 | 判空跳过本次采样 |
| `OpenProcess` 失败 | 系统进程、受保护进程 | 判空句柄，记 `(unknown)` |
| 未声明 `argtypes` | 64 位下句柄截断，随机失败 | 全部显式声明 |
| `LASTINPUTINFO.cbSize` 未赋值 | 永远返回 0，误判"一直在用" | 赋值 |
| 标题频繁变化 | 见 V0.7 的切分策略 | 本版先记录，不切分 |
| 采样线程异常静默死掉 | 日志停止但程序还在 | V0.3 的 `threading.excepthook` 兜住 |

---

## 验收标准

- [ ] 切换不同程序，日志里能看到对应的 `app` 与 `title`
- [ ] 截图工具 / 计算器（UWP）能记录到（哪怕是 `ApplicationFrameHost.exe` 也要有记录）
- [ ] 锁屏 6 分钟回来，日志里能看到空闲时长超过 300 秒
- [ ] 托盘"暂停"后不再产生采样记录，"恢复"后继续
- [ ] 连续跑 30 分钟，日志无异常、无内存暴涨

---

## 完成后你应当能回答

- 为什么采样不能放在主线程？
- `GetLastInputInfo` 的返回值为什么能代表"用户是否在用电脑"？
- 64 位 Python 下不声明 `argtypes` 会发生什么？
- UWP 应用为什么会被记成同一个进程？

---

## 参考文件

`windows/info-collect/win/winapi.py`（全部 Win32 签名与封装）、`win/sampler.py`（采样循环）。
