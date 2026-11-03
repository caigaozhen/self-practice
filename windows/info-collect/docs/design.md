# InfoCollect —— 时间去向记录器

记录"我一天的时间都花在哪了"的 Windows 常驻小程序。

- 状态：**v0.3 已完成**（采集 → 落库 → 报表 → 上报 → 托盘 → 自启 → 配置界面 → exe 打包 → 版本资源与交付打磨）
- 定位：**只给自己用**（不做用户体系、不做多租户、不上架）
- 第三方依赖：**零**（托盘/图标/界面全是 ctypes + 标准库手写）
- 父目录：`F:\self-practice\windows\`

---

## 快速开始

> 本文所有 `py -3 -X utf8 app.py ...` 命令都在 **`win/`** 目录下执行。
> 项目分三块：`win/`（Windows 采集端）、`mobile/`（手机端）、`supabase/`（云端建表）。

### 日常使用（推荐）

```bash
# 1. 双击 start_silent.bat —— 无窗口启动，右下角出现托盘图标
#    或者直接双击 dist\InfoCollect\InfoCollect.exe（打包版）

# 2. 右键托盘图标 → 菜单
#    查看今日报表 / 打开配置界面 / 暂停采集 / 立即推送 / 开机自启 / 退出
#    左键双击 = 直接看今日报表

# 3. 不要再用了：右键 → 退出，或双击 stop.bat
```

### 想装开机自启

两种方式，效果一样：

- 双击 `install_autostart.bat`
- 或在配置界面勾选「登录 Windows 时自动启动」再保存

> 写的是 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，
> **不需要管理员权限**，卸载就是删掉那一行，不碰系统任何其它地方。
> 检查当前状态：`py -3 -X utf8 app.py autostart status`

### 命令行（调试用）

```bash
cd win

# 前台采集，有黑窗口，Ctrl+C 停止
py -3 -X utf8 app.py run

# 看报表（有控制台就打印，没有就开窗口）
py -3 -X utf8 app.py report
py -3 -X utf8 app.py report --date 2026-10-30 --window

# 配置 / 状态 / 自启 / 推送 / 清库
py -3 -X utf8 app.py ui
py -3 -X utf8 app.py status
py -3 -X utf8 app.py autostart on|off|status
py -3 -X utf8 app.py upload --dry-run
py -3 -X utf8 app.py wipe --yes
```

数据在 `%APPDATA%\InfoCollect\infocollect.db`，用任意 SQLite 工具都能打开，见 §13。上报机制见 §12。

---

## 1. 一句话目标

> 登录后在后台静默运行，记录每个前台程序占用了多少时间、在干什么，按类别汇总，随时能问"今天时间花哪了"。

---

## 2. 已经定下来的决策

| 项 | 决定 | 影响 |
|---|---|---|
| 使用者 | 只有我自己 | 不用做登录/注册/权限体系；数据可以单设备 |
| 统计对象 | **全量前台程序**（不是只盯编码类） | 需要"分类映射"这一层，否则报表是一堆 exe 名 |
| 采集口径 | **L2**：进程名 + 键鼠活跃度 + 窗口标题（截断 120 字） | 能区分"在 PyCharm 写哪个项目"；**不过滤**，尽量采 |
| 标题黑名单 | **默认关闭**（空列表），但机制保留 | 想开只需改配置，不用改代码 |
| idle 阈值 | **300 秒**，可配置 | 5 分钟没碰键鼠算离开 |
| 存储 | 本地 SQLite 优先 | 上报是可选增强，不做也能用 |
| 上报 | **已实现**：定时（默认 4 小时）+ 关机时各推一次；失败保留待补传 | 见 §12 |
| 发布形态 | 源码 + bat（要 Python）与 PyInstaller exe（不需要）**都可用** | **同一套代码**，靠 `sys.frozen` 区分，不是重写 |
| 常驻方式 | 托盘图标 + 无窗口（`tray` 子命令） | 关掉窗口不再等于停止采集 |
| 开机自启 | `HKCU\...\Run`，不需要管理员 | 与 bootstat 同一套机制，见 §14.3 |
| 依赖 | **零第三方** | 托盘、图标、界面全部手写，见 §7 |

---

## 3. 发布形态：两种形态，一套代码

### 形态一：源码 + bat（要 Python）

目标机需要装 Python。好处是改代码立即生效，调试最快。

```bat
start "" pythonw "F:\...\app.py" tray
```

### 形态二：exe（目标机不需要 Python）· 已实现

PyInstaller 把**解释器和代码一起塞进 exe**，用户机器上没装过 Python 也能跑。

```
pyinstaller --noconfirm --onedir --windowed --name InfoCollect ^
            --icon infocollect.ico --add-data "infocollect.ico;." app.py
```

产出 `dist\InfoCollect\`（约 30MB），双击 `InfoCollect.exe` 直接进托盘。
`build_exe.bat` 把这些参数和检查都包好了，实测 15 秒构建完成。

### 关键认知：这不是"两套代码"

阶段二只是**换个方式启动同一堆 .py 文件**。但有 4 个地方必须从阶段一就写对，否则打包时会一夜之间全崩：

| 隐患 | 错误写法（源码能跑，exe 崩） | 正确写法 |
|---|---|---|
| 定位程序目录 | `Path(__file__).parent` | `Path(sys.executable).parent`（冻结后 `__file__` 指向解压临时目录） |
| 自启动命令 | 无条件写 `pythonw + app.py` | 判断 `getattr(sys, "frozen", False)`，两个分支各写一种 |
| 配置文件位置 | 放程序同级目录 | 一律 `%APPDATA%\InfoCollect\`（exe 可能在只读目录） |
| 子进程自重启 | `subprocess.Popen([sys.executable, __file__])` | 冻结后 `sys.executable` 是 exe 自己，参数要换 |

> 打包参数说明：用 `--onedir` 不要 `--onefile`。onefile 每次启动都要自解压到临时目录，慢 1~3 秒，且极易被杀软误报。常驻程序尤其受不了这个启动延迟。

### 被否决的方案：embeddable Python

Python 官方的 embeddable 版（约 11MB 的 zip）能让"bat 版也不需要装 Python"。但它**默认不含 tkinter、不含 pip**，跟"点开能配置"的需求直接冲突，放弃。

---

## 4. 数据模型

### 4.1 核心表 `sessions`

不按"每 60 秒一条"存，而是按**一段连续活跃**存一条。切换程序或闲置时结算。

```sql
CREATE TABLE sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts    INTEGER NOT NULL,   -- Unix 秒（UTC）
    end_ts      INTEGER NOT NULL,
    app         TEXT    NOT NULL,   -- 进程名，如 pycharm64.exe
    title       TEXT,               -- 会话代表标题（见 §6.3）
    category    TEXT    NOT NULL,   -- 分类结果，如「编码」
    device_id   TEXT    NOT NULL,   -- 机器标识，为将来多设备预留
    uploaded    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_sessions_start ON sessions(start_ts);
CREATE INDEX idx_sessions_app   ON sessions(app);
```

**为什么不用固定采样行**：一天 5 秒采样一次是 17280 行，全是碎片；而会话式一天通常只有 200~800 行，查询天然就是"时间区间求和"。

### 4.2 `meta` 表

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
-- last_heartbeat  最后一次成功采样的时间戳，用于发现"程序断了"
-- schema_version  预留给将来迁移（当前代码未写入）
```

### 4.3 数据量估算

| 粒度 | 一天行数 | 一年体积 |
|---|---|---|
| 会话式（切换才结算） | 200 ~ 800 | < 5 MB |
| 固定 60 秒采样 | ~600 | ~22 MB |

两种都毫无压力，选会话式是为了**查询简单**。

---

## 5. 核心机制：采样状态机

这是整个程序的心脏。默认每 5 秒采集一次，判断"还是不是同一段工作"：

```
每 5 秒：

  ① 取「上次键鼠动作距今多久」→ idle_seconds
  ② 若 idle_seconds > 阈值（默认 300 秒）：
        结算当前会话（end_ts = 最后活跃时刻），进入「闲置态」，等下轮
  ③ 否则取「当前前台进程名 + 标题」→ (app, title)
  ④ 若 app 相同且 title 属于同一"工作单位"：
        继续累加（什么都不做，只是不结算）
  ⑤ 若 app 或工作单位变了：
        结算旧会话 → 开新会话
```

### 必须处理的边界

| 边界 | 处理 |
|---|---|
| **锁屏** | 主动检测（`OpenInputDesktop` 失败即锁屏），比只靠 idle 判断更准 |
| **休眠 / 睡眠** | 醒来后检测到 `now - 上轮采样时间 > 60 秒`，说明中间不连续 → 丢弃这段，不补记 |
| **时钟跳变** | 时间差为负时 clamp 到 0，并丢弃该区间（NTP 校准、手动改时间会触发） |
| **进程崩溃** | 启动时检查 `last_heartbeat`，若与当前时间差 > 10 分钟，说明上次异常退出 → 补一条"数据缺口"标记 |
| **重复启动** | 命名 Mutex 做单实例锁，否则自启动 + 手动开 = 双倍统计 |
| **全屏视频** | 全屏 + 长时间无输入，会被误判为闲置。可选优化：识别全屏窗口，用较宽的 idle 阈值 |

---

## 6. 采集口径详解

### 6.1 Windows 上能拿到的 7 个信号

前 5 个都是零成本（一次 API 调用，微秒级）。

| # | 信号 | 怎么拿 | 能回答什么 | 坑 |
|---|---|---|---|---|
| 1 | **键鼠活跃度** | `user32.GetLastInputInfo` | 人还在不在 | 看视频、开会时不碰键鼠 → 判成闲置 |
| 2 | **前台窗口句柄** | `user32.GetForegroundWindow` | 只给一个 HWND，本身没意义 | — |
| 3 | **前台进程名** | `GetWindowThreadProcessId` → PID → `QueryFullProcessImageNameW` | 在用什么软件（分类的核心依据） | UWP 应用拿到的是 `ApplicationFrameHost.exe`（见 §6.4） |
| 4 | **窗口标题** | `user32.GetWindowTextW` | 在干什么（哪个项目、哪个网页） | 自由文本，天然含敏感信息 |
| 5 | **窗口类名** | `user32.GetClassNameW` | 比标题稳定，可判"浏览器/对话框/游戏" | 名字怪，如 `Chrome_WidgetWin_1` |
| 6 | 是否全屏 | 窗口矩形 vs 显示器尺寸 | 在看视频/打游戏 | 多显示器要逐屏判断 |
| 7 | 会话锁定状态 | `OpenInputDesktop` | 人是不是真的离开了 | 拿不到句柄 = 已锁屏 |

**拿不到的两个**（成本高、易碎，建议不做）：

- **浏览器 URL**：要读地址栏，得用 UI Automation 或写浏览器扩展。浏览器 UI 一改就废
- **文件保存事件**：要监控目录，太重，且无法归因到"是谁保存的"

### 6.2 三档方案

| 档位 | 采集内容 | 能回答的问题 | 代价 |
|---|---|---|---|
| L1 最小 | ①③ | 今天在哪个软件上花了多久 | 最低 |
| **L2 推荐（选定）** | ①③④⑤ | 在 PyCharm 里是写哪个项目、浏览器在看什么站 | 要做脱敏 |
| L3 深度 | L2 + ⑥⑦ | 看视频算不算工作、精确的离开时刻 | 复杂度上升，误判变多 |

选 L2 的理由：只用进程名的话，报表会是这样——

```
pycharm64.exe   4 小时 12 分
chrome.exe      2 小时 30 分
```

看不出任何东西。加了标题之后——

```
编码 · info-collect 项目        2 小时 40 分
编码 · bootstat 项目            1 小时 32 分
浏览 · 飞书文档 / 数据库设计      1 小时 05 分
沟通 · 微信                      48 分
```

这才是"时间花哪了"。

### 6.3 窗口标题的设计（这是隐私的关键）

标题是自由文本，会包含文件名、网址、聊天对象、邮件主题、甚至密码管理器的条目名。所以必须做四件事：

**① 长度截断** —— 统一截到 120 字符，防止某个网页标题特别长把库撑爆

**② 黑名单机制保留，但默认不启用**

已决定：尽量采集，不做的额外过滤。`title_blacklist` 配置项存在，默认是空列表，代码里会照常走过滤逻辑，只是没有规则命中。

将来如果想排除某些程序，只需在配置里加一条，**不用改代码**：

```json
"title_blacklist": ["keepass.exe", "*bank*"]
```

代价要说清楚：不开过滤意味着标题里可能出现聊天对象名、邮件主题、网银页面标题这类内容。自己用没问题，但别让 `%APPDATA%` 那份数据库被同步到网盘或云端备份。

**③ 只存"会话代表标题"，不存每秒快照** —— 会话结束时取出现最多的那个标题。这样一小时里翻了 200 个网页，库里只有一条"代表标题"，既省空间也不像监控日志。

**④ 可随时整体关闭** —— 配置项 `collect_window_title: true`，关掉就退化成 L1。

> 一个折中思路（如果以后觉得太敏感）：加一层"标题归一化"——把 `bootstat.py - PyCharm` 这种归一化成 `PyCharm`，只保留"项目名"部分。但这样也丢失了区分度，先按原样存。

### 6.4 三个必须知道的坑

**① UWP 应用拿到的进程名是错的**

Windows 上的"应用商店应用"（设置、计算器、照片、微软商店）都跑在一个叫 `ApplicationFrameHost.exe` 的宿主进程里。你 `GetForegroundWindow` 拿到的进程名永远是它，而不是真实应用。

解法：枚举该窗口的**子窗口**，找那个不属于 `ApplicationFrameHost` 的进程。

```python
user32.EnumChildWindows(hwnd, callback, 0)   # 对每个子窗口取 PID，取真实进程
```

如果只是自己用，可以先用"标题"补救：设置应用的标题通常是"设置"，能认出来。但分类会不准。

**② 管理员权限的程序，非管理员拿不到进程名**

你以普通用户身份运行 InfoCollect，而前台是一个以管理员身份启动的程序（某些游戏、安装程序）时，`OpenProcess` 会失败，进程名拿不到。

兜底：进程名取失败就记成 `unknown.exe`，别让它把程序搞崩。

**③ `GetLastInputInfo` 里是 32 位 tick，会回绕**

```python
lii.dwTime          # 32 位 tick（GetTickCount 的返回值）
idle_ms = GetTickCount() - lii.dwTime      # 超过 49.7 天会算出负数
```

处理方式：`(GetTickCount64() - lii.dwTime) & 0xFFFFFFFF`，或者对负数结果 clamp 到 0。这个坑和 `bootstat` 里 `GetTickCount64` 的 `restype` 问题是同一类——**Windows 的时间 API 全是坑**。

**④ 中文标题会让控制台/日志乱码**

实测标题原文是 `管道漏水噪声记录仪论文推荐 - 豆包`，直接在 cmd 里 `print` 会变成 `<50535050726F...>` 这样的十六进制乱码（终端编码是 GBK/cp936，而 Python 输出 UTF-8）。

处理方式：

- 程序内部一律用 `str`，**不要**按字节处理
- 写日志时显式指定编码：`logging.FileHandler(path, encoding="utf-8")`
- 命令行打印时加 `py -3 -X utf8`，或者在代码开头 `sys.stdout.reconfigure(encoding="utf-8")`

如果不处理，最直接的后果是：**数据库里存的中文标题全是问号**，而且你会以为是 API 取错了，白排查半天。

### 6.5 代码骨架（ctypes 部分）

```python
import ctypes
from ctypes import wintypes

user32   = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

def get_idle_seconds() -> float:
    lii = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    now = kernel32.GetTickCount64()
    diff = (now - lii.dwTime) & 0xFFFFFFFF      # 处理回绕
    return diff / 1000.0

def get_foreground() -> tuple[str, str]:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ("", "")
    # 标题
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    title = buf.value
    # 进程名
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    app = ""
    if h:
        pbuf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
            app = pbuf.value.rsplit("\\", 1)[-1].lower()
        kernel32.CloseHandle(h)
    return (app or "unknown.exe", title)
```

### 6.6 实测结论（本机，2026-10-30）

上面三个 API 都已跑通，真实输出：

```
idle=   5.2s   app=msedge.exe   cls=Chrome_WidgetWin_1   title=管道漏水噪声记录仪论文推荐 - 豆包
idle=   0.4s   app=msedge.exe   cls=Chrome_WidgetWin_1   title=（同上）
```

| 项 | 结论 |
|---|---|
| `GetLastInputInfo` | 正常，能反映"多久没碰键鼠"（两次采样间隔 1 秒，idle 从 6.2s 降到 0.4s，说明中间有输入） |
| `GetForegroundWindow` + 进程名 | 正常，拿到了 `msedge.exe` |
| `GetWindowTextW` | 正常，能拿到完整中文标题（注意编码坑，见 §6.4 ④） |
| `GetClassNameW` | 正常，Edge 的类名是 `Chrome_WidgetWin_1` |
| `OpenInputDesktop`（锁屏检测） | **未实测**。解锁状态下返回非 0 句柄（588），锁屏时应返回 0，但这条需要实际锁屏才能验证 |

这台机器的实测数据还证明了"标题采集"的价值——光看 `msedge.exe` 你只知道"在浏览"，看了标题才知道"在查某个技术论文"。同时它也是一记警钟：标题直接暴露了具体工作内容。

以上能力已固化到 `winapi.py`，并补了三样文档里没细说的处理：

- UWP 宿主穿透（`ApplicationFrameHost.exe` → 枚举子窗口找真实进程）
- 权限不足兜底（`OpenProcess` 失败 → `unknown.exe`，不崩溃）
- 32 位 tick 回绕（`& 0xFFFFFFFF`）

模块自带自测入口，可以直接观察现场数据。

---

## 7. 模块划分

```
info-collect/
├── README.md              导航页
├── win/                   Windows 采集端
│   ├── app.py                 入口：argparse、单实例锁、日志、12 个子命令
│   ├── config.py              配置读写 + APP_VERSION
│   ├── winapi.py              ctypes 封装：idle / 前台进程 / 标题 / 锁屏
│   ├── sanitize.py            标题截断、黑名单、工作单位归一化
│   ├── store.py               SQLite：建表、开/结会话、待上传队列
│   ├── sampler.py             采样状态机（核心）
│   ├── classifier.py          进程名 → 分类映射
│   ├── reporter.py            文本/结构化报表
│   ├── uploader.py            上报：generic / supabase 两种协议
│   ├── shutdown.py            捕获关机/注销/关窗口事件
│   ├── autostart.py           开机自启（区分源码/exe 两种形态）
│   ├── tray.py                托盘图标（纯 ctypes Shell_NotifyIcon）
│   ├── icon.py                纯 Python 生成 .ico（无 Pillow）
│   ├── ui_common.py           界面公共：DPI 感知、居中、置前、字体
│   ├── ui_config.py           tkinter 配置窗
│   ├── ui_report.py           tkinter 报表窗（无控制台时用）
│   ├── make_version_info.py   生成 exe 版本资源（v0.3）
│   ├── version_info.txt       版本资源生成物（不要手改）
│   ├── infocollect.ico        图标（由 icon.py 生成，也可当 exe 图标）
│   ├── InfoCollect.spec       PyInstaller 配置
│   ├── *.bat                  8 个双击入口（含 build_exe.bat）
│   └── dist/InfoCollect/      打包产物（exe 在这里）
├── mobile/                手机端（uni-app · Vue3 + Vite）
│   ├── src/pages/             主界面 / 连接设置
│   ├── src/utils/             纯函数 + Supabase 访问层
│   └── README.md
├── supabase/              云端
│   ├── schema.sql             建表 + RLS + 聚合视图
│   ├── push_fn.sql            只更新上报函数
│   └── README.md
├── dev/                   本地测试（不交付）
│   ├── mock_server.py         假服务端（支持 generic 与 PostgREST 两种）
│   ├── test_format.mjs        手机端纯函数测试
│   └── test_upload_protocol.py 上报协议端到端测试
└── docs/
    ├── requirements.md        需求分析
    ├── database-design.md     数据库设计
    ├── detailed-design.md     详细设计
    ├── operations.md          部署与运维（含开机自启）
    ├── design.md              本文档：设计决策与踩坑
    └── dev-workflow.md        开发流程
```

### 依赖方向（单向，无循环）

```
app.py
 ├── config.py        （无依赖）
 ├── winapi.py        （无依赖，纯 ctypes）
 ├── shutdown.py      （无依赖，纯 ctypes）
 ├── tray.py          （无依赖，纯 ctypes）
 ├── icon.py          （无依赖，纯 stdlib）
 ├── autostart.py     （无依赖，winreg + subprocess）
 ├── sanitize.py      （依赖 config 的黑名单）
 ├── store.py         （依赖 config 拿路径）
 ├── sampler.py       （依赖 winapi + sanitize + store + classifier + uploader）
 ├── reporter.py      （依赖 store）
 ├── uploader.py      （依赖 store，用 urllib 发 POST）
 ├── classifier.py    （无依赖）
 └── ui_*.py          （依赖 config / store / reporter / autostart，只在开窗时导入）
```

**第三方依赖：零。** 托盘、图标、界面全部用 ctypes 和标准库手写。
这不是洁癖：每多一个包，`pip install` 就多一个失败点，PyInstaller 打包就多
一个 hidden-import 坑，而这两个动作都在"换台机器"的时候发生——那时候你
最不想调环境。

---

## 8. 隐私与数据边界

| 原则 | 具体做法 |
|---|---|
| 标题黑名单默认关闭 | 已决定"尽量采"；机制保留，需要时改配置即可开启 |
| 标题只存代表值 | 一小时只留一条，不留逐秒快照 |
| 不采集按键内容 | 只用 `GetLastInputInfo` 拿"距上次输入的毫秒数"，不碰任何按键 |
| 不上传原始数据 | 将来上报只传 `app + category + 时长`，不传标题 |
| 数据可随时清空 | 提供 `--wipe` 命令 |
| 本机数据库不加密但放在用户目录 | `%APPDATA%` 默认只有当前用户可读 |
| 配置界面不外发任何数据 | 唯一联网的地方是 `uploader.py`，且只在启用上报时 |

自己用的工具容易松懈，但这份数据本质上是**行为日志**，一旦被同步、备份到别处，泄露面比想象的大。

---

## 9. 配置项

```json
{
  "sample_interval_seconds": 5,
  "idle_threshold_seconds": 300,
  "collect_window_title": true,
  "title_max_length": 120,
  "title_blacklist": [],
  "split_by_title": true,
  "work_unit_chars": 40,
  "app_level_apps": [
    "chrome.exe", "msedge.exe", "firefox.exe", "iexplore.exe",
    "360se.exe", "qqbrowser.exe", "safari.exe"
  ],
  "switch_confirm_samples": 3,
  "category_map": {
    "pycharm64.exe": "编码",
    "code.exe": "编码",
    "windowsterminal.exe": "编码",
    "chrome.exe": "浏览",
    "wechat.exe": "沟通",
    "explorer.exe": "文件管理"
  },
  "default_category": "其他",
  "autostart": false,
  "device_label": "",
  "upload": {
    "enabled": false,
    "provider": "generic",
    "endpoint": "",
    "token": "",
    "include_title": false,
    "interval_hours": 4,
    "on_shutdown": true,
    "timeout_seconds": 10,
    "batch_size": 500
  }
}
```

配置存放：`%APPDATA%\InfoCollect\config.json`
——不放程序目录，因为 exe 可能装在只读位置。

**不要手改也行**：双击 `config_ui.bat` 或托盘菜单「打开配置界面」，
保存后 30 秒内自动生效（见 §14.4），不用重启进程。

几个关键旋钮：

| 键 | 作用 | 调大会怎样 |
|---|---|---|
| `idle_threshold_seconds` | 多久没碰键鼠算离开 | 更容易判为"还在工作"，虚高 |
| `sample_interval_seconds` | 采样间隔 | 精度下降，CPU 占用下降 |
| `switch_confirm_samples` | 切换程序要连续几次采样才确认 | 碎片更少，但归属会有几秒延迟 |
| `app_level_apps` | 这些程序不按标题切分 | 缓解浏览器标题频变导致的碎片 |
| `split_by_title` | 会话是否按标题首段切分 | 关掉后变成"一个程序一段" |
| `category_map` | 进程名 → 分类 | 新装的程序一律进"其他"，加一行即可 |

`title_blacklist` 默认空数组表示"什么都采"，过滤逻辑仍会执行，只是没有规则命中。

`config.load()` 会把用户配置合并到 `DEFAULTS` 上，所以**老配置文件缺字段不会崩**，
新增字段也不用写迁移脚本。

---

## 10. 待定项

| # | 问题 | 状态 |
|---|---|---|
| 1 | "同一工作单位"怎么判定 | ✅ 已实现：标题首段切分 + 浏览器按程序切分 + 粘滞确认 |
| 2 | 分类是手动配，还是内置一套常见程序规则 | ✅ 内置 15 条常见规则，可覆盖 |
| 3 | 报表以什么形式看 | ✅ v0.1 为 `report` 纯文本，图形化待定 |
| 4 | 是否需要"番茄钟/休息提醒" | ⬜ v2 再说 |
| 5 | 云上报什么时候做 | ✅ 已实现定时 + 关机推送（§12），默认关闭 |
| 6 | 全屏视频要不要特殊处理 | ⬜ 先不处理，观察误判率 |
| 7 | 浏览器要不要区分到"站点"级别 | ⬜ 需要做标题解析，先不做 |

---

## 11. 开发进度

v0.1 的目标是**能看见数字**，v0.2 的目标是**能天天用**。全部完成：

**v0.1 — 采集闭环**

1. ✅ `winapi.py`：`get_idle_seconds()` / `get_foreground()` / `is_locked()`
2. ✅ `store.py`：建表 + 开/结会话 + 心跳 + 残留补结算
3. ✅ `sampler.py`：状态机（粘滞切换、断档检测、闲置回填）
4. ✅ `reporter.py`：分类占比 + 程序排行 + 明细
5. ✅ `app.py`：单实例锁 + 日志 + 子命令
6. ✅ `start.bat` / `report.bat`：双击可用
7. ✅ `uploader.py` + `shutdown.py`：定时推送、关机推送、失败保留
8. ✅ `mock_server.py`：本地假服务端，没真服务器也能验证上报

**v0.2 — 常驻与交付**

9. ✅ `icon.py`：纯 Python 生成多尺寸 .ico（4×4 超采样做抗锯齿）
10. ✅ `tray.py`：纯 ctypes 托盘（图标 / 动态 tooltip / 右键菜单 / 气泡通知）
11. ✅ `autostart.py`：源码与 exe 两种形态的自启命令生成 + 写注册表 + 陈旧检测
12. ✅ `ui_config.py`：配置界面（校验到字段、保存即热更新）
13. ✅ `ui_report.py`：报表窗口（分类/程序/明细三页 + ← → 切日期 + 复制文本）
14. ✅ `app.py`：新增 `tray` / `stop` / `ui` / `autostart` 子命令
15. ✅ `build_exe.bat`：一键打包，实测产出 30MB / 15 秒
16. ✅ `WM_QUERYENDSESSION`：无控制台形态下关机仍能结算

**v0.3 — 交付打磨**

17. ✅ `config.APP_VERSION`：版本号单一来源，`status` / 托盘菜单 / 日志 / 上报客户端标识统一
18. ✅ `make_version_info.py` + `build_exe.bat --version-file`：exe 文件属性显示版本
19. ✅ `build_exe.bat` 补拷 `report.bat`；`report.bat` 适配 exe（走报表窗口而不是 `app.py`）
20. ✅ 启动自启体检：路径失效/位置不一致时写日志 + 托盘通知 + 菜单「点此修复」
21. ✅ `install_excepthook()`：windowed exe 的未捕获异常写入日志
22. ✅ 新增 `docs/requirements.md` / `database-design.md` / `detailed-design.md` / `operations.md`

### 已验证的行为

| 场景 | 预期 | 实测 |
|---|---|---|
| 切换程序 | 结算旧会话，开新会话 | ✅ 结束时刻 = 切换时刻 |
| 换项目（同一 IDE） | 按标题首段切成两段 | ✅ `bootstat.py` 与 `info-collect 设计` 分开 |
| 离开电脑 5 分钟 | 结算，且结束时刻回填到最后一次输入 | ✅ 结束于 +100s 而非 +400s |
| 休眠后唤醒 | 判定断档，不补记这段时间 | ✅ 断在最后一次采样，之后重新开段 |
| 浏览器标题频变 | 不产生碎片 | ✅ 6 段碎片 → 合并为 1 段 |
| 单实例 | 第二个进程被拒绝 | ✅ 命名互斥体 |
| 定时上报 | 到点自动推，不阻塞采集 | ✅ 待上传 2 → 0 |
| 上报失败 | 数据保留，不丢 | ✅ 返回 0，待上传仍为 1 |
| 退出/关机 | 结算当前会话后再推一次 | ✅ 待上传 1 → 0，服务端收到 payload |
| 托盘图标 | 出现且能弹出菜单 | ✅ 截图确认，灰色表头/勾选/分隔线正常 |
| 托盘菜单"暂停" | 结算当前会话，之后只写心跳 | ✅ `sampler.pause()/resume()` |
| 配置热更新 | 保存后 30 秒内生效 | ✅ 间隔 5→11、闲置 300→60 均生效 |
| 自启写入/删除 | 命令含 pythonw 和 `tray` 参数 | ✅ 用临时值名测，未碰真实启动项 |
| 崩溃后重启 | 自动补结算残留会话 | ✅ 日志`补结算了 1 条上次残留的会话` |
| 关机（无控制台） | 收到 `WM_QUERYENDSESSION` 并结算 | ✅ `end_ts` 由 0 变为实际时间 |
| exe 双击 | 直接进托盘，不留隐形进程 | ✅ 冻结形态默认 `tray` |
| `stop` 子命令 | 让托盘实例正常退出 | ✅ 窗口消失，会话已结算 |
| exe 版本资源 | 属性显示 `0.3.0.0` / 产品名 / 描述 | ✅ `VersionInfo.FileVersion` 实测 |
| 新 exe 启动 | 日志出现 `InfoCollect v0.3 托盘模式启动（打包 exe）` | ✅ 重启托盘后实测 |
| 交付目录 | 含 6 个 bat（含 `report.bat`） | ✅ 列目录确认 |
| 自启体检 | 路径失效时日志 warning + 托盘通知 | 逻辑已实现，待构造失效场景复测 |

### `winapi.py` 的设计约定（其它模块都遵守）

- **不抛异常**：失败返回兜底值（`unknown.exe` / 空串 / `0.0` / `False`），调用方不用写 `try`
- **不 print、不写日志**：纯数据获取，方便单测
- **返回 dataclass `Foreground`**：字段是"空串而非 None"

### 待真实验收

连续跑 2 小时，`report` 出来的总时长与实际感知误差小于 10%，且没有单条超过 3 小时的异常会话。

---

## 12. 上报服务端

### 三个触发点

| 触发 | 时机 | 超时 | 说明 |
|---|---|---|---|
| **定时** | 每 `interval_hours`（默认 4 小时） | 3 秒 | 后台线程发，不阻塞采集 |
| **关机** | 系统关机 / 注销 / 关闭控制台窗口 | 2 秒 | 尽力而为，来不及就放弃 |
| **启动补传** | 程序启动时若发现有待上传数据 | 3 秒 | 兜底：上次关机没推成功的，这次补上 |

另外 `py -3 app.py upload` 可手动推一次，`--dry-run` 只打印不发送。

### 可靠性怎么保证

**关键认知：关机推送靠不住，`uploaded` 标记才是真保障。**

Windows 关机时只给控制台程序 3~5 秒（超时直接 terminate），一次 HTTPS 请求未必来得及完成。所以设计成：

```
推送成功 → 才把 uploaded 置 1
推送失败 → uploaded 保持 0，数据留在本地
下次启动 → 发现待上传，自动补推
```

也就是说：**关机推送只是"让服务端早点看到数据"，不是数据完整性的保障。** 最坏情况下数据延迟到下次启动才上传，但不会丢。

实测过的三条路径：

| 场景 | 结果 |
|---|---|
| 定时到点 | 待上传 2 → 0 |
| 服务端不可达 | 返回 0，待上传仍为 1（数据保留） |
| 退出时推送 | 待上传 1 → 0 |

### 协议

```http
POST <endpoint>
Authorization: Bearer <token>
Content-Type: application/json; charset=utf-8
```

```json
{
  "client": "InfoCollect/0.3",
  "device_id": "11f77d7a5cb7",
  "sent_at": 1793343678,
  "sessions": [
    {"id": 2, "start_ts": 1793339677, "end_ts": 1793341477,
     "app": "pycharm64.exe", "title": "bootstat.py - PyCharm",
     "category": "编码", "device_id": "11f77d7a5cb7"}
  ]
}
```

成功返回任意 2xx 即可，客户端不解析响应体。

### 服务端必须做幂等

**按 `(device_id, id)` 做 upsert，不要直接 INSERT。** 因为客户端可能重发同一批（例如服务端写库成功但响应超时，客户端认为失败会重试）。不幂等的话，你的统计会翻倍。

### 本地测试

```bash
py -3 -X utf8 mock_server.py        # 监听 127.0.0.1:8765，只打印不落库
```

它会把收到的 JSON 格式化打印出来，用来验证"字段对不对、条数对不对、token 带没带"。

### 为什么不能直连数据库

exe 可以被反编译出源码和配置，**任何硬编码在客户端的数据库密码都等于公开**。所以客户端只带一个可撤销的 token，真实写库发生在你的服务端。

---

## 13. 查看数据库

数据文件：`%APPDATA%\InfoCollect\infocollect.db`
在资源管理器地址栏粘贴 `%APPDATA%\InfoCollect` 就能打开目录。

### 方式一：命令行（推荐，Python 自带 sqlite3）

```bash
py -3 -c "import sqlite3,os; c=sqlite3.connect(os.path.expandvars(r'%APPDATA%\InfoCollect\infocollect.db')); [print(r) for r in c.execute('SELECT id,start_ts,end_ts,app,title FROM sessions ORDER BY id DESC LIMIT 20')]"
```

### 方式二：图形工具

**DB Browser for SQLite**（免费）：打开 `infocollect.db` → 浏览数据 → 选 `sessions` 表。
注意采集程序在跑的时候也能同时打开（用了 WAL 模式）。

### 常用查询

```sql
-- 今天每段会话（时间戳转本地时间）
SELECT datetime(start_ts,'unixepoch','localtime') AS 开始,
       datetime(end_ts,'unixepoch','localtime')   AS 结束,
       end_ts - start_ts                          AS 秒数,
       app, category, title
FROM sessions
WHERE end_ts > strftime('%s','now','localtime','start of day')
ORDER BY start_ts;

-- 今天各分类总时长（分钟）
SELECT category, SUM(end_ts - start_ts) / 60 AS 分钟
FROM sessions
GROUP BY category ORDER BY 分钟 DESC;

-- 今天各程序排行
SELECT app, SUM(end_ts - start_ts) / 60 AS 分钟, COUNT(*) AS 段数
FROM sessions
GROUP BY app ORDER BY 分钟 DESC LIMIT 20;

-- 检查有没有异常长会话（> 3 小时），用于发现"忘了停表"
SELECT id, datetime(start_ts,'unixepoch','localtime'), (end_ts-start_ts)/3600.0 AS 小时
FROM sessions WHERE end_ts - start_ts > 10800;
```

> `end_ts = 0` 表示那段会话还没结束（程序被强杀时会残留），下次启动会自动补结算。

---

## 14. v0.2 实现说明：托盘 / 自启 / 配置界面 / 打包

### 14.1 托盘：为什么手写而不是用 pystray

托盘不是"一个控件"，它背后只有**一条 API**：`Shell_NotifyIconW`。机制是：

```
注册窗口类 → 创建一个不可见的窗口 → 告诉外壳"图标挂在这个 hWnd 上"
          → 用户点图标，外壳给这个窗口发消息 → WNDPROC 里弹菜单
```

窗口必须存在，因为外壳要靠 `hWnd` 知道鼠标消息该发给谁。

手写的代价是 250 行 ctypes，收益是**零依赖**：不用装 pystray，也就不会
连带引入 Pillow，PyInstaller 打包时少两个 hidden-import 坑。

**过程中踩的坑（很典型）**：第一版直接调 `DefWindowProcW` 就报
`OverflowError: int too long to convert`。原因是 ctypes 默认把未声明的
参数当 32 位 `c_int`，而 `LPARAM` 是 64 位。这种错误发生在回调里，只会
打印一句 `Exception ignored`，界面看起来"只是有点怪"，极难定位。所以
`tray.py` 里有一个 `_declare()`，把所有 API 的 `argtypes/restype` 全部
显式声明了——**64 位下这不是讲究，是必需**。

### 14.2 关机推送：v0.1 的预言成真了

v0.1 的文档里写过一句预告：

> 换 `pythonw` / exe 后 `SetConsoleCtrlHandler` 失效，关机推送需要改成
> 隐藏窗口 + `WM_QUERYENDSESSION`。

事实确实如此。`pythonw.exe` 和 `--windowed` 的 exe **没有控制台**，
`SetConsoleCtrlHandler` 注册了也不会被调用。所以托盘窗口自己接：

```python
elif msg == WM_QUERYENDSESSION:     # 系统问"可以关机吗"
    self.on_endsession("query")     # 必须同步做完收尾，返回值一给出就会被终止
    return 1                        # TRUE = 不阻止关机
```

实测（模拟发送该消息）：会话立刻结算，日志出现
`收到系统关机/注销通知（query），开始收尾`，`end_ts` 从 0 变成实际时间。

即便如此，仍然遵循原设计：**关机推送只是尽力而为**，真正的保障是
「推送成功才置 `uploaded=1`，失败留在本地，下次启动补传」。

### 14.3 自启：两种形态，一个判断

```python
源码形态：  "C:\...\pythonw.exe" "F:\...\app.py" tray
打包形态：  "C:\...\InfoCollect.exe" tray
```

判断依据是 `sys.frozen`。**源码形态必须挑一个带 tkinter 的解释器**——
这是从 bootstat 继承的教训（当时默认解释器没 tkinter，弹窗退化成系统对话框）。
`autostart.pick_interpreter()` 会起子进程去试 `import tkinter`，因为当前进程
自己可能就是缺 tkinter 的那个。

`install()` 是可重复执行的：它用 `Path(__file__).resolve()` 取自己的当前位置，
所以移动目录后重新执行一次就修好了。`status` 会检测"注册表里的路径已经不存在"
（`stale`）并提示修复。

### 14.4 配置界面：改完不用重启

配置窗口保存后只做一件事：写 `config.json`（原子替换）。托盘进程有一个
30 秒的定时器，比对文件 mtime：

```python
if mtime != last_mtime:
    cfg.clear(); cfg.update(config.load())    # 就地改同一个 dict
    sampler.apply_config(cfg)                  # 重算派生参数
    up.apply_config(cfg)                       # 上传参数同样要刷
```

**关键细节**：`cfg` 是构造 Sampler/Uploader 时传进去的同一个 dict 对象，
所以必须**就地改**（`clear` + `update`），不能 `cfg = config.load()` 重新绑定——
后者只改了局部名字，那两个对象还指着旧 dict。同时 `Sampler.interval` 这类
派生值在 `__init__` 里就算好了，必须用 `apply_config()` 重算一遍。

实测：改完 30 秒内生效，日志出现
`配置已热更新：间隔 11s，闲置阈值 60s`。

### 14.5 打包：`--onedir`，不要 `--onefile`

```bash
py -3 -m PyInstaller --noconfirm --clean --onedir --windowed \
    --name InfoCollect --icon infocollect.ico \
    --add-data "infocollect.ico;." app.py
```

| 参数 | 为什么 |
|---|---|
| `--onedir` | 常驻程序不要用 `--onefile`：每次启动都要解压到临时目录，慢 1~3 秒，且更容易被杀软误报 |
| `--windowed` | 不分配控制台，等价于 pythonw。副作用是 `print` 全部丢失，`sys.stdout is None` |
| `--add-data` | 图标跟 exe 同目录，程序用 `sys.executable` 的父目录去找它 |

实测产物 30MB（`_internal` 里大头是 tcl/tk + Python 运行时），构建 15 秒。

**打包后必须注意的两处代码**，否则源码能跑、exe 崩：

```python
# ✗ Path(__file__) 在 onefile 下指向临时解压目录，每次启动都不同
# ✓ 用 sys.executable
program_dir() = Path(sys.executable).parent if is_frozen() else Path(__file__).parent

# ✗ 双击 exe 没有参数 → 会走进 cmd_run（前台采集）
# ✓ 冻结形态默认进托盘，否则会变成一个没有窗口、没有托盘、也关不掉的隐形进程
if args.cmd is None and is_frozen():
    return cmd_tray(False)
```

### 14.6 一个容易被忽略的 UI 坑

从托盘拉起窗口时，Windows 不允许后台进程随便抢焦点，窗口经常开在别的窗口
后面——用户以为"点了没反应"。解法是临时置顶 250ms 再取消：

```python
win.attributes("-topmost", True)
win.after(250, lambda: win.attributes("-topmost", False))
```

**但必须先 `update()` 让窗口真正映射出来再置顶**。对一个还没显示的窗口设置
`-topmost`，Windows 会把窗口丢回默认的层叠位置，之前算好的居中坐标白算
（实测从 `(620,170)` 变成 `(78,78)`）。这个 bug 只能靠对比截图发现。

### 14.7 已知边界

| 边界 | 现状 | 影响 |
|---|---|---|
| 关机推送 | `WM_QUERYENDSESSION` 里同步推送，超时 2 秒 | 网络慢时可能失败，靠下次启动补传 |
| 托盘刷新 | 30 秒一次 | 提示条数字有最多 30 秒延迟，菜单里的数字是实时的 |
| 多用户 | 每个用户各自一份数据 + 各自的 Run 键 | 只有自己用，不处理 |
| 高 DPI | 已开 Per-Monitor V2 | 极端缩放比下字体可能偏小 |
| 双击 exe 无参数 | 默认托盘 | 想看报表请用右键菜单里那一项 |

### 14.8 v0.3：把「能用」变成「可交付、可维护」

v0.2 已经能天天用，但交付层面还有几个坑。v0.3 只做打磨，没有改采集口径：

**① 版本号单源**

之前 win 端完全没有版本号，只能靠文件修改时间猜。现在 `config.APP_VERSION` 是唯一来源：

```
config.APP_VERSION
  ├── app.py status / 日志 / 托盘菜单
  ├── uploader.CLIENT_TAG（上报时告诉服务端客户端版本）
  └── make_version_info.py → version_info.txt → PyInstaller --version-file
```

`build_exe.bat` 每次先跑 `make_version_info.py`，所以不会出现「界面是新版、exe 属性是旧版」。

**② 打包补漏**

`report.bat` 之前没被拷进 `dist\InfoCollect\`，而且它只会调 `app.py`——在只有 exe 的机器上
双击必然失败。现在 `report.bat` 先检测同目录的 `InfoCollect.exe`，有就用
`report --window` 开窗口，没有才退回 Python。

**③ 自启失效不再静默**

自启是最容易「看起来没问题、实际早就坏了」的部分：移动目录、Python 升级都会让
注册表指向不存在的路径，而 windowed 进程失败时没有任何提示。v0.3 在托盘启动时做一次
`autostart.diagnose()`：

- 路径不存在 → 日志 warning + 托盘通知；
- 命令与当前位置不一致 → 同样提示；
- 菜单项从「开机自启」切换为「开机自启：路径已失效，点此修复」，点击后用当前 exe 重写。

**④ 未捕获异常落盘**

`--windowed` 的 exe 没有控制台，异常默认只会让托盘图标消失。`install_excepthook()`
把 `sys.excepthook` 接到日志，至少留下堆栈；日志本身失败时吞掉异常，避免二次崩溃。

---

## 15. 待办

| 项 | 说明 |
|---|---|
| 服务端实现 | 目前只有协议约定，可以写个 FastAPI 收数据（需要一个后台任务） |
| 分类映射自动学习 | 现在新装的程序一律进"其他"，需要手动加一行 |
| 周/月汇总视图 | 报表窗目前只能按天看（← → 切日期） |

---

## 附：与 bootstat 项目的关系

`bootstat`（`../bootstat/`）已经验证过的部分可以直接复用：

- 写 `HKCU\...\Run` 的自启动机制，以及 `best_interpreter()` 挑解释器的逻辑
- `pythonw.exe` 静默运行的坑（无 stdout，必须写日志）
- 「绝对路径脆弱」的教训（别把路径指向临时目录）

区别在于：`bootstat` 是一次性执行的短命进程，本项目是**长期驻留**，所以多了单实例、心跳、优雅退出这些新问题。
