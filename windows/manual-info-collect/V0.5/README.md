# V0.5 · 托盘图标与右键菜单

> **一句话目标**：程序常驻后，通知区出现一个图标；右键能弹出菜单（至少"打开日志"和"退出"）；退出时图标干净消失。

到这一版，它才第一次"像个程序"——有可见的存在感，也有可控的退出方式。

---

## 前置条件

V0.4 完成：单实例锁生效。

---

## 核心难点：托盘需要窗口

`Shell_NotifyIconW` 不是一个独立控件，它要求你提供一个 **`hWnd`**，图标上的鼠标事件会以**窗口消息**的形式投递到这个窗口。

所以顺序是：

```
注册窗口类 → 创建（隐藏）窗口 → 加托盘图标 → 跑消息循环
```

这也解释了为什么托盘程序的主线程必须是**消息循环线程**：Win32 的窗口和它的消息队列绑定在创建它的线程上，`GetMessageW` 只在那个线程能取到属于它的消息。

---

## 要做什么

### 1. 隐藏窗口

`RegisterClassW` + `CreateWindowExW`，`hwndParent = 0`，不调用 `ShowWindow` 就自然是隐藏的。

窗口过程（`WNDPROC`）里处理：

| 消息 | 处理 |
|---|---|
| `WM_APP + 1`（自定义） | 托盘事件，见下 |
| `WM_DESTROY` | `PostQuitMessage(0)` |

### 2. 加图标：`Shell_NotifyIconW(NIM_ADD, &nid)`

`NOTIFYICONDATAW` 结构体关键字段：

| 字段 | 值 |
|---|---|
| `cbSize` | `sizeof(NOTIFYICONDATAW)`（**必填，错了直接失败**） |
| `hWnd` | 上面创建的隐藏窗口句柄 |
| `uID` | 自定义整数，如 `1` |
| `uFlags` | `NIF_MESSAGE | NIF_ICON | NIF_TIP` |
| `uCallbackMessage` | `WM_APP + 1` |
| `hIcon` | `LoadIconW(None, IDI_APPLICATION)`（先用系统图标，V0.5 不做自定义 ico） |
| `szTip` | 鼠标悬停文本，`ctypes.create_unicode_buffer("ManualInfoCollect")` |

### 3. 右键菜单

收到 `WM_APP+1` 且 `lParam == WM_RBUTTONUP` 时：

```
CreatePopupMenu()
AppendMenuW(menu, MF_STRING, 1, "打开日志")
AppendMenuW(menu, MF_STRING, 2, "退出")
SetForegroundWindow(hwnd)          ← 少了这句，菜单点外面不消失
GetCursorPos(&pt)
TrackPopupMenu(menu, TPM_RIGHTBUTTON, pt.x, pt.y, 0, hwnd, None)
DestroyMenu(menu)
```

`TrackPopupMenu` 的返回值就是被点中的菜单项 ID，据此分发动作。

### 4. 退出时删图标

`Shell_NotifyIconW(NIM_DELETE, &nid)`，否则图标会变成"幽灵"——鼠标划过才消失，直到你重启 explorer。

### 5. explorer 重启后重新加图标

任务栏崩溃重启后，所有托盘图标都会丢。系统会广播一个消息：

```
msg = RegisterWindowMessageW("TaskbarCreated")
if msg and message == msg:  重新 NIM_ADD
```

不做这一步的表现是：某次 explorer 崩过之后，图标就再也回不来了。

---

## 实现步骤

1. 定义 `NOTIFYICONDATAW`（ctypes.Structure，注意字段顺序与类型要对齐）
2. 定义 `WNDPROC`（`ctypes.WINFUNCTYPE`），处理 `WM_APP+1` / `WM_DESTROY` / `TaskbarCreated`
3. `RegisterClassW` + `CreateWindowExW` 建隐藏窗口
4. `NIM_ADD` 加图标
5. 消息循环 `GetMessageW → TranslateMessage → DispatchMessageW`
6. 菜单动作：退出时 `NIM_DELETE` + `DestroyWindow` + `PostQuitMessage`

**调试技巧**：先在窗口过程里把收到的 `msg` 打到日志，确认消息真的到达，再写菜单逻辑。不要一次写完再调。

---

## 坑

| 坑 | 表现 | 处理 |
|---|---|---|
| `cbSize` 不对 | `NIM_ADD` 返回 0，无图标 | 用 `ctypes.sizeof()` 赋值 |
| 未定义 `argtypes/restype` | 64 位下句柄被截断成 32 位，静默失效 | 关键 API 一律声明签名 |
| 少 `SetForegroundWindow` | 菜单弹出后点别处不消失 | 见上文 |
| 退出不 `NIM_DELETE` | 幽灵图标 | 退出路径统一处理 |
| 窗口过程被 GC | 消息收不到 / 崩溃 | WNDPROC 对象要模块级持有 |
| 消息循环跑错线程 | 图标存在但点击无反应 | 创建窗口与消息循环同线程 |
| 不处理 `TaskbarCreated` | explorer 重启后图标永久消失 | 见上文 |

---

## 验收标准

- [ ] 启动后通知区出现图标，悬停显示提示文字
- [ ] 右键弹出菜单，点"打开日志"能打开日志文件
- [ ] 点"退出"后：进程结束、图标立即消失（无幽灵图标）
- [ ] 在任务管理器里重启 `explorer.exe`，图标能自动回来
- [ ] 与 V0.4 的单实例锁共存：第二次启动被拦，不产生第二个图标

---

## 完成后你应当能回答

- 为什么托盘必须依附一个窗口？
- 为什么消息循环必须在主线程？
- `WM_APP` 是什么，为什么用它而不是随便找个消息号？
- 为什么 64 位下必须显式声明 `argtypes`？

---

## 参考文件

`windows/info-collect/win/tray.py`（完整托盘实现）、`win/icon.py`（.ico 加载与转换）。
