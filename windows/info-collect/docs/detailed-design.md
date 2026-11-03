# InfoCollect 详细设计

> 文档定位：面向实现与排障，说明「模块怎么切、关键流程怎么走、边界怎么处理」。
> 需求见 [requirements.md](requirements.md)，存储见 [database-design.md](database-design.md)，
> 部署操作见 [operations.md](operations.md)，历史决策见 [design.md](design.md)。
>
> 版本：v0.3（2026-11-02）

---

## 1. 总体架构

```
┌──────────────────────────── Windows 采集端（win/）────────────────────────────┐
│                                                                              │
│  app.py（入口 / 12 个子命令 / 单实例锁 / 日志 / 托盘装配）                    │
│    │                                                                         │
│    ├── winapi.py       ctypes：idle / 前台进程 / 标题 / 锁屏                  │
│    ├── sampler.py      采样状态机（核心）                                     │
│    │     ├── sanitize.py    标题截断 / 黑名单 / 工作单位                      │
│    │     ├── classifier.py  进程名 → 分类                                     │
│    │     └── store.py       SQLite（唯一 SQL 层）                             │
│    ├── reporter.py     按天聚合；ui_report.py 表格窗口                        │
│    ├── uploader.py     generic / supabase 两种上报协议                        │
│    ├── autostart.py    HKCU Run 写入 / 检测 / 解释器选择                      │
│    ├── tray.py         ctypes Shell_NotifyIcon 托盘                           │
│    ├── icon.py         纯 Python 生成 .ico                                    │
│    └── ui_config.py    配置窗口                                               │
│                                                                              │
│  数据目录 %APPDATA%\InfoCollect\：config.json / infocollect.db / infocollect.log│
└──────────────────────────────────────────────────────────────────────────────┘
                 │ 可选 HTTPS POST
                 ▼
┌────────────── Supabase ──────────────┐        ┌────────── mobile/ ──────────┐
│ sessions + v_daily + v_devices       │◀───────│ 登录后只读（authenticated） │
│ push_sessions(rows jsonb)            │        │ 日期 / 设备筛选 / 三页签     │
│ RLS：anon 只 insert，authenticated 只读│        └─────────────────────────────┘
└──────────────────────────────────────┘
```

依赖方向是单向的：`app.py` 依赖各功能模块；功能模块只依赖更底层的模块，
没有循环依赖。`winapi.py`、`tray.py`、`icon.py`、`autostart.py` 不依赖业务模块。

---

## 2. 运行形态与进程/线程模型

### 2.1 两种运行形态，一套代码

| 形态 | 启动方式 | 判断 |
|---|---|---|
| 源码 | `py -3 -X utf8 app.py tray`，或 `start_silent.bat` | `sys.frozen` 为 False |
| 打包 exe | `dist\InfoCollect\InfoCollect.exe`（无参数默认 `tray`） | `sys.frozen` 为 True |

冻结后必须遵守的四条规则（否则源码能跑、exe 崩）：

| 隐患 | 错误写法 | 正确写法 |
|---|---|---|
| 程序目录 | `Path(__file__).parent` | `Path(sys.executable).parent` |
| 自启命令 | 无条件写 `pythonw + app.py` | 判断 `sys.frozen`，有 exe 优先用 exe |
| 配置位置 | 放程序同级目录 | 一律 `%APPDATA%\InfoCollect\` |
| 子进程启动 | `[sys.executable, __file__]` | 冻结后 `sys.executable` 就是 exe 自己，参数改为子命令 |

### 2.2 `tray` 模式的线程/进程模型

```
主线程：Tray.run()
  ├── 注册窗口类 → 创建隐藏窗口 → Shell_NotifyIcon(NIM_ADD)
  ├── on_start()：启动自启体检（v0.3）
  ├── SetTimer(30s)：配置热更新 + 刷新 tooltip
  └── GetMessage 循环：托盘菜单 / 双击 / WM_QUERYENDSESSION

采样线程（daemon）：Sampler.run_forever()
  └── 每 interval 秒 tick()，内部可能派生上传线程

上传线程（按需）：
  ├── 定时推送：Sampler.tick → Uploader.maybe_periodic → Thread(push_once)
  ├── 启动补传：run_forever 启动时 Thread(push_once)
  └── 关机推送：Sampler._finalize → Uploader.push_on_exit（同步、短超时）

界面进程（按需，独立进程）：
  spawn("report", "--window") / spawn("ui")
  原因：托盘消息循环占用主线程，tkinter 不能在主线程里再开窗口
```

为什么采样不能放主线程：Win32 窗口和消息队列绑定在创建它的线程上，
托盘消息循环必须占住主线程；采样是死循环，只能分线程。这也是 `Store`
需要 `check_same_thread=False` + `RLock` 的原因。

单实例：命名互斥体 `InfoCollect_SingleInstance`。第二个进程拿不到锁会被拒绝，
避免「开机自启 + 手动双击」重复记录。

### 2.3 子进程启动命令

`app.launcher_cmd()`：

- 冻结形态：`[sys.executable]`
- 源码形态：`[带 tkinter 的 pythonw, app.py 绝对路径]`

`spawn()` 用 `CREATE_NO_WINDOW` 启动，避免闪黑框。

---

## 3. 模块职责

| 文件 | 职责 | 关键点 |
|---|---|---|
| `app.py` | 入口、argparse、单实例锁、日志、托盘装配、12 个子命令 | `install_excepthook`（v0.3）；配置热更新 |
| `config.py` | 路径与配置读写；默认值合并；`APP_VERSION` | 原子替换写入；`INFOCOLLECT_HOME` 覆盖 |
| `winapi.py` | idle / 前台进程 / 标题 / 类名 / 锁屏 | 不抛异常，失败返回兜底值；UWP 穿透；tick 回绕 |
| `sampler.py` | 采样状态机、会话开关、心跳、暂停、收尾 | 粘滞切换、闲置回填、断档检测 |
| `store.py` | SQLite 建表、会话读写、待上传队列、心跳 | 唯一 SQL 层；RLock；WAL |
| `sanitize.py` | 标题截断、黑名单、工作单位归一化 | 纯字符串，无 Windows API |
| `classifier.py` | 进程名 → 分类 | 精确匹配、大小写不敏感 |
| `reporter.py` | 按天聚合与文本排版 | 跨天按重叠时长 |
| `uploader.py` | 两种 provider 的组包与推送 | 成功才标记；失败保留；线程安全 |
| `autostart.py` | 自启命令生成、注册表读写、诊断 | exe 优先；陈旧检测；解释器挑选 |
| `shutdown.py` | 控制台关机/注销回调 | 仅控制台形态有效；超时短 |
| `tray.py` | 手写托盘、菜单、气泡通知、关机消息 | 全部 API 显式声明 argtypes |
| `icon.py` | 纯 Python 生成多尺寸 .ico | 无 Pillow |
| `ui_common.py` | DPI、居中、置前、字体 | `bring_to_front` 先 update 再置顶 |
| `ui_config.py` | 配置窗口、校验、保存、测试推送 | 保存后热更新 |
| `ui_report.py` | 报表窗口（分类/程序/明细） | Treeview 对齐中文；← → 切日期 |
| `make_version_info.py` | 生成 exe 版本资源（v0.3） | 版本号单源 `config.APP_VERSION` |

---

## 4. 关键流程

### 4.1 采样状态机（核心）

状态只有两种：

```
空闲态  sid == 0
会话态  sid != 0，正在累加 start_ts / key / titles
```

每 `interval` 秒执行一次 `Sampler.tick(now)`：

```text
① 暂停态？
     写心跳（保持"运行中"），直接返回

② 时间断档？
     now - last_tick > max(3 × interval, 30)
     → 结束当前会话于 last_tick（不补记休眠时间）
     → 写心跳，返回

③ 人还在不在？
     idle = get_idle_seconds(); locked = is_locked()
     locked 或 idle >= idle_threshold
     → 若有会话：close(now - min(idle, now))   # 回填到最后一次输入
     → 写心跳，返回

④ 取前台窗口
     失败（切换瞬间 / 锁屏过渡）→ 只更新 last_tick，返回，不误判换程序

⑤ 计算 key = (app, work_unit(app, title))

⑥ 判断是否同一段工作
     sid == 0                 → open(now, app, title, category)
     key == 当前 key           → 清空待确认；titles[title] += 1
     key 不同                  → 计数待确认；连续 sticky 次后：
                                  at = max(start_ts + 1, pending_at)
                                  close(at); open(at, app, title, category)

⑦ last_tick = now；写心跳（30 秒一次）
⑧ uploader.maybe_periodic(now)   # 到点则派生后台推送线程
```

状态迁移：

| 当前 | 条件 | 动作 | 结果 |
|---|---|---|---|
| 空闲 | 活跃且有前台窗口 | `open` | 会话态 |
| 会话 | 同一 `(app, work_unit)` | 累加标题计数 | 会话态 |
| 会话 | 新 key 连续 `sticky` 次 | `close(pending_at)` + `open(pending_at)` | 会话态（新） |
| 会话 | idle 超阈值 / 锁屏 | `close(最后输入时刻)` | 空闲态 |
| 会话 | 时间断档 | `close(last_tick)` | 空闲态 |
| 会话 | 暂停 / 退出 / 关机 | `close(now)` | 空闲态 |

为什么需要「待确认切换」：浏览器里点几下、Alt+Tab 瞄一眼微信，都会产生几秒的碎片。
连续 3 次采样确认后，才把切换时刻回填到新程序首次出现的时刻，不丢时间也不重叠。

### 4.2 会话结算与代表标题

- 会话开启：插入 `end_ts = 0` 的行，记录 `sid`、`start_ts`、`key`、`titles = Counter()`。
- 会话期间：每轮把当前标题计数 +1（标题为空则不计）。
- 结算：取 `titles.most_common(1)` 作为代表标题，`close_session(sid, end_ts, title)`。
- `close_session` 用 `MAX(end_ts, start_ts + 1)`，不会出现零长度或负长度。
- 这样一小时翻 200 个网页只留一条代表标题，既省空间也不像逐秒监控日志。

### 4.3 上报流程

触发点：

| 触发 | 入口 | 线程 | 超时 |
|---|---|---|---|
| 定时 | `Sampler.tick → Uploader.maybe_periodic` | 后台线程 | `timeout_seconds`（默认 10） |
| 启动补传 | `Sampler.run_forever` 发现 pending > 0 | 后台线程 | 默认 |
| 关机/注销/退出 | `Sampler._finalize → Uploader.push_on_exit` | 调用线程（同步） | `min(timeout, 2)` |
| 手动 | `app.py upload` / 托盘「立即推送」 | 当前/后台线程 | 默认 |

单次推送：

```text
push_once()
  ├── ready?（enabled 且 endpoint 以 http(s) 开头）否则返回 0
  ├── 获取 _lock（1 秒超时）→ 已有推送则跳过
  ├── pending_sessions(batch_size) → 无数据返回 0
  ├── build_payload（generic 信封 / supabase {"rows": [...]}）
  ├── POST → 2xx?
  │     ├── 是：mark_uploaded(ids)；记录 last_upload_at/count；返回条数
  │     └── 否/异常：记录 warning，返回 0，数据保留
  └── 释放锁
```

一致性：至少一次投递 + 云端 `(device_id, id)` 幂等 → 不重不漏。
关机推送只是「让服务端早点看到」，**数据完整性的真正保障是 `uploaded` 标记 + 下次启动补传**。

### 4.4 开机自启（v0.3 含启动体检与修复）

#### 命令生成

`autostart.launcher_command(mode)`：

| mode | 行为 |
|---|---|
| `auto`（默认） | 有打包 exe 就用 exe；没有才退回 `pythonw + app.py` |
| `exe` | 必须找到 exe，否则抛错 |
| `python` | 强制源码形态（改代码调试时用） |

两种形态写出的命令：

```text
打包：  "C:\...\InfoCollect.exe" tray
源码：  "C:\...\pythonw.exe" "F:\...\app.py" tray
```

优先 exe 的原因：源码形态把某个 `pythonw.exe` 的绝对路径钉死，Python 升级/卸载/venv
删除后开机静默失效；exe 自带解释器，与本机 Python 环境解耦。

`packaged_exe()` 的候选位置：

```text
<program_dir>\InfoCollect.exe
<program_dir>\dist\InfoCollect\InfoCollect.exe
```

#### 注册表

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
  InfoCollect = "<绝对路径>" tray
```

仅当前用户，不需要管理员。`install()` 可重复执行；移动目录后重跑一次即可修复。

#### 诊断 `diagnose()`

返回：

| 字段 | 含义 |
|---|---|
| `enabled` | 注册表值是否存在 |
| `command` | 当前写入的命令 |
| `expected` | 按当前位置应写入的命令 |
| `frozen` | 是否打包形态 |
| `exe` | 找到的 exe 路径（可能为空） |
| `stale` | 命令中的 `.exe` / `.py` 路径是否已不存在 |
| `missing_tk` | 源码形态下是否找不到带 tkinter 的解释器 |

#### v0.3 启动体检与一键修复

托盘启动、图标挂上之后（`Tray.on_start`）：

```text
info = state["auto"]（启动时 diagnose 一次，配置热更新时刷新）
if enabled and stale:
    日志 warning「开机自启体检：...」
    托盘通知「开机自启已失效」→ 菜单出现「开机自启：路径已失效，点此修复」
elif enabled and command != expected:
    通知「开机自启指向旧位置」
elif not enabled and config.autostart == true:
    通知「开机自启未生效」
```

修复动作 `repair_autostart()`：用当前位置重新 `set_enabled(True)`，写回配置并刷新状态。
菜单中的「开机自启」项在正常情况下是勾选开关，失效时变成修复入口。

为什么必须主动体检：自启失效是**静默**的——`pythonw` / windowed exe 没有控制台，
失败没有任何报错，只能靠日志里的「最后心跳」事后发现。

### 4.5 配置热更新

```
配置窗口保存 → config.json 原子替换
托盘 30 秒定时器 → 比对 mtime
  → cfg.clear(); cfg.update(config.load())    # 就地改同一个 dict
  → sampler.apply_config(cfg)                  # 重算 interval / idle / sticky 等派生值
  → up.apply_config(cfg)
  → state["auto"] = autostart.diagnose()       # v0.3：自启状态同步
```

关键细节：`cfg` 是构造 `Sampler` / `Uploader` 时传入的同一个 dict 对象，
必须就地修改，不能 `cfg = config.load()` 重新绑定，否则那两个对象仍指向旧 dict。
`Sampler.interval` 等派生值在 `__init__` 里算好，必须由 `apply_config()` 重算。

### 4.6 托盘与窗口

- 托盘图标用 `Shell_NotifyIconW` 手写，不引入 pystray/Pillow。
- 隐藏窗口类 `InfoCollectTrayWnd`，`stop` 子命令通过 `FindWindowW` + `WM_CLOSE` 让它正常退出。
- 菜单每次右键重新构建，所以「今日时长 / 待上传条数」是实时的。
- 菜单项：今日统计、待上传、查看报表、打开配置、立即推送、暂停、开机自启（或修复）、
  打开数据目录、版本号（v0.3，禁用项）、退出。
- 左键双击 = 查看今日报表；左键单击 = 刷新提示。
- 窗口从托盘拉起时先 `update()` 映射，再临时 `-topmost` 250ms，否则会开在别的窗口后面。
- 托盘 tooltip 每 30 秒刷新；菜单里的数字每次都重新查库（使用独立 `Store` 连接，避免抢锁）。

### 4.7 关机 / 注销收尾

| 形态 | 机制 | 是否有效 |
|---|---|---|
| 源码 `run`（有控制台） | `SetConsoleCtrlHandler` 捕获 `CTRL_SHUTDOWN/LOGOFF/CLOSE` | 是 |
| 源码 `tray` / 打包 exe（无控制台） | 托盘窗口接收 `WM_QUERYENDSESSION` / `WM_ENDSESSION` | 是 |
| 被任务管理器强杀 | 无回调 | 否；靠下次启动 `close_dangling` 补结算 |

`Sampler._finalize()` 用 `_finalized` 保证只执行一次：结算当前会话 → 写心跳 →
`push_on_exit()`（短超时）→ 日志「采样已停止」。

### 4.8 exe 打包

`build_exe.bat`：

```bat
py -3 -X utf8 make_version_info.py       :: 生成 version_info.txt（版本号来自 config.APP_VERSION）
py -3 -m PyInstaller --noconfirm --clean --onedir --windowed --name InfoCollect ^
    --icon infocollect.ico --add-data "infocollect.ico;." ^
    --version-file version_info.txt app.py
copy 6 个 bat 到 dist\InfoCollect\
```

| 参数 | 原因 |
|---|---|
| `--onedir` | 常驻程序不用 `--onefile`：onefile 每次启动自解压到临时目录，慢 1~3 秒，且易被杀软误报 |
| `--windowed` | 不分配控制台（等价 pythonw）；双击 exe 默认进托盘 |
| `--add-data` | 图标随 exe 分发 |
| `--version-file` | v0.3：让 exe 文件属性显示版本 |

交付目录内容（v0.3）：

```
dist\InfoCollect\
├── InfoCollect.exe          （带版本资源）
├── _internal\               （Python 运行时、Tcl/Tk、sqlite3 等）
├── infocollect.ico
├── start_silent.bat         启动托盘
├── stop.bat                 正常退出
├── config_ui.bat            配置界面
├── report.bat               报表窗口（v0.3 修复为 exe 感知）
├── install_autostart.bat    开启自启
└── uninstall_autostart.bat  关闭自启
```

---

## 5. 接口设计

### 5.1 命令行子命令

| 子命令 | 作用 |
|---|---|
| `run` | 前台采集（有控制台，Ctrl+C 停止） |
| `tray` | 托盘常驻（开机自启用这个） |
| `ui` | 配置界面 |
| `stop` | 让托盘实例正常退出 |
| `report [--date YYYY-MM-DD] [--tail N] [--window]` | 报表 |
| `status` | 版本、路径、自启、上报、待上传、心跳 |
| `config` | 打印当前配置 JSON |
| `autostart on/off/status [--python]` | 自启管理 |
| `upload [--dry-run]` | 手动推送 |
| `cloud [--ping] [--dry-run]` | 云端配置与连通性自检 |
| `device [--label NAME]` | 本机标识与显示名 |
| `wipe [--yes]` | 清空本地会话 |

### 5.2 配置结构

见 `win/config.py` 的 `DEFAULTS`。关键字段：

| 字段 | 默认 | 说明 |
|---|---|---|
| `sample_interval_seconds` | 5 | 采样间隔 |
| `idle_threshold_seconds` | 300 | 闲置阈值 |
| `collect_window_title` | true | 是否采集标题 |
| `title_max_length` | 120 | 标题截断 |
| `title_blacklist` | `[]` | 默认不过滤 |
| `split_by_title` | true | 是否按标题首段切分 |
| `work_unit_chars` | 40 | 工作单位保留字符数 |
| `app_level_apps` | 浏览器列表 | 这些程序不按标题切分 |
| `switch_confirm_samples` | 3 | 切换粘滞次数 |
| `category_map` | 内置 21 条 | 进程名 → 分类 |
| `default_category` | 其他 | 未命中分类 |
| `autostart` | false | 与注册表同步的记录值 |
| `device_label` | "" | 本机显示名 |
| `upload.*` | 见下 | 上报配置 |

`upload` 段：

| 字段 | 默认 | 说明 |
|---|---|---|
| `enabled` | false | 总开关 |
| `provider` | generic | generic / supabase |
| `endpoint` | "" | generic 填完整接口；supabase 填项目根地址 |
| `token` | "" | generic 填设备 token；supabase 填 anon key |
| `include_title` | false | 是否上传标题 |
| `interval_hours` | 4 | 定时推送间隔 |
| `on_shutdown` | true | 关机时最后推一次 |
| `timeout_seconds` | 10 | 单次超时 |
| `batch_size` | 500 | 单批条数 |

配置加载：`config.load()` 把用户配置合并到 `DEFAULTS`，缺字段自动补齐，老配置不会崩。

### 5.3 模块接口

`Store`（`win/store.py`）：

| 方法 | 作用 |
|---|---|
| `open_session(start_ts, app, title, category) -> int` | 开启会话，返回 id |
| `close_session(sid, end_ts, title=None)` | 结算，`MAX(end_ts, start_ts+1)` |
| `heartbeat(ts)` / `last_heartbeat()` | 心跳 |
| `close_dangling(end_ts) -> int` | 补结算残留会话 |
| `pending_sessions(limit) -> list[dict]` | 待上传队列 |
| `pending_count() -> int` | 待上传条数 |
| `mark_uploaded(ids)` | 标记成功 |
| `sessions_between(t0, t1, now_ts) -> rows` | 与区间重叠的会话 |
| `device_id()` / `device_label()` / `set_device_label()` | 本机标识 |
| `wipe()` | 清空会话 |

`Sampler`：

| 方法 | 作用 |
|---|---|
| `tick(now=None)` | 单次采样（核心） |
| `run_forever()` | 启动补结算 / 补传 / 循环 |
| `pause()` / `resume()` | 暂停/恢复（暂停只写心跳） |
| `apply_config(cfg)` | 热更新派生值 |
| `shutdown(reason)` | 收尾（幂等） |

`Uploader`：

| 方法 | 作用 |
|---|---|
| `ready` | 配置齐全 |
| `status_text()` | 人类可读状态 |
| `build_payload(items)` | 组包（两种 provider） |
| `push_once(timeout=None, dry_run=False) -> int` | 推一批 |
| `maybe_periodic(now)` | 到点派生后台线程 |
| `push_on_exit()` | 退出时短超时推送 |
| `apply_config(cfg)` | 热更新 |

`autostart`：

| 函数 | 作用 |
|---|---|
| `is_frozen()` / `program_dir()` / `packaged_exe()` | 形态与路径 |
| `pick_interpreter() -> (python, has_tk)` | 源码形态挑解释器 |
| `launcher_command(mode)` | 生成注册表命令 |
| `install(mode)` / `uninstall()` / `set_enabled(on, mode)` | 写/删 |
| `current_value()` / `is_enabled()` | 读 |
| `diagnose() -> dict` | 诊断 |

### 5.4 HTTP 协议

见 [database-design.md](database-design.md) §5。摘要：

- generic：`POST endpoint`，`Authorization: Bearer <token>`，信封 JSON。
- supabase：`POST /rest/v1/rpc/push_sessions`，`apikey` + `Authorization`，`{"rows": [...]}`。
- 成功判定：HTTP 2xx；supabase 响应体为实际写入行数（重复时为 0，仍算成功）。

---

## 6. 并发与一致性

| 共享资源 | 保护方式 | 说明 |
|---|---|---|
| SQLite 连接 | `Store._lock`（RLock） | 采样、上传、关机回调可能并发 |
| 当前会话状态 | `Sampler._slock`（RLock） | 防止主线程暂停/关机回调与采样线程撞车 |
| 推送 | `Uploader._lock` | 同一时刻只允许一个 push；拿不到锁就跳过 |
| 单实例 | 命名互斥体 | 进程级 |
| 配置对象 | 就地 `clear + update` | 所有持有者看到同一份新值 |
| 心跳/上传元数据 | `meta` 表 upsert | `ON CONFLICT DO UPDATE` |

幂等点：

- `Sampler._finalize` 的 `_finalized` 标志：关机消息与控制台回调可能同时触发。
- `close_session` 的 `MAX`：时间跳变/负值时兜底。
- 云端 `on conflict do nothing`：重发不重复。
- `mark_uploaded` 批量 `WHERE id = ?`：重复标记无副作用。

---

## 7. 异常处理与日志

| 层 | 策略 |
|---|---|
| `winapi.py` | 不抛异常，失败返回 `unknown.exe` / 空串 / `0.0` / `False` |
| `sampler.tick` | 外层 `try/except`，异常记日志并跳过本轮，不中断循环 |
| `uploader` | 捕获 HTTP/网络/JSON 异常，记 warning，返回 0；绝不影响采集 |
| `store` | 写失败由调用方吞掉或记日志；`close()` 吞异常 |
| `tray` WNDPROC | 整体 try/except，异常写日志，返回 `DefWindowProc` |
| 顶层 | v0.3 `install_excepthook()` 把未捕获异常写入日志（windowed exe 唯一的线索） |
| 日志 | `RotatingFileHandler`，2MB × 3，UTF-8；控制台日志仅在 `sys.stderr` 存在时添加 |

日志级别约定：启动/会话结算/推送成功用 INFO；推送失败、自启体检异常用 WARNING；
每轮结算细节用 DEBUG（`-v` 才输出）。

---

## 8. 安全与隐私实现

| 原则 | 实现 |
|---|---|
| 不采集按键内容 | 只用 `GetLastInputInfo` 拿「距上次输入的毫秒数」 |
| 标题可控 | `collect_window_title` 总开关；`title_blacklist` 机制保留（默认空） |
| 只存代表标题 | `Counter.most_common(1)` |
| 默认不上传标题 | `upload.include_title = false`，上传时传空串 |
| 密钥不硬编码数据库密码 | 桌面端只带可撤销 token / anon key，写库走 RPC + RLS |
| 数据可清空 | `wipe` / 手动删除数据目录 |
| 网络最小化 | 唯一联网点是 `uploader.py`，且仅在启用上报时 |

---

## 9. 测试与验收对应

| 层 | 命令 | 覆盖 |
|---|---|---|
| L1 纯函数 | `node dev/test_format.mjs` | 手机端时长/日期/聚合，24 个断言 |
| L2 协议端到端 | `py -3 -X utf8 dev/mock_server.py --postgrest 8766` + `py -3 -X utf8 dev/test_upload_protocol.py 8766` | endpoint 归一化、payload 形状、首推、重推幂等 |
| 手工验收 | [design.md](design.md) §11 | 采集口径、托盘、自启、关机、配置热更新 |
| v0.3 新增 | [requirements.md](requirements.md) §8.1 | 版本属性、打包完整、自启体检/修复、异常日志 |

改动后至少执行：

```bash
py -3 -m py_compile win\*.py
node dev\test_format.mjs
```

---

## 10. 已知限制与后续

| 限制 | 现状 | 后续 |
|---|---|---|
| 全屏视频误判闲置 | 未特殊处理 | 观察误判率，再决定是否按全屏窗口放宽阈值 |
| 管理员权限程序拿不到进程名 | 记为 `unknown.exe` | 可接受；不建议为此提权 |
| 浏览器不区分站点 | 按程序聚合 | 需要标题解析或扩展，成本高 |
| 周/月汇总 | 仅按天 | v2 可加 |
| 服务端缺失 | 只有协议约定 | 可写 FastAPI 接收端 |
| 分类自动学习 | 未命中归「其他」 | 需人工加映射 |
| 版本资源需手动重建 | `build_exe.bat` 生成 | 发版时统一执行 |
