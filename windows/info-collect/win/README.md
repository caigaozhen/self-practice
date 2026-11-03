# win · Windows 采集端

采集「前台是哪个程序、多久没碰键鼠、窗口标题是什么」，切成会话存进本地 SQLite。

当前版本：**v0.3**（版本号唯一来源是 `config.APP_VERSION`）。

## 三种启动方式

| 方式 | 命令 / 文件 | 特点 |
|---|---|---|
| 托盘（日常） | 双击 `start_silent.bat` | 无窗口，右下角图标 |
| 前台（调试） | 双击 `start.bat` | 有黑窗口，能看到日志，Ctrl+C 停 |
| exe（无 Python 的机器） | `dist\InfoCollect\InfoCollect.exe` | 拷走整个 `dist\InfoCollect` 即可 |

退出用托盘菜单的「退出」或 `stop.bat`。**别用任务管理器强杀**——那样当前这段会话的 `end_ts` 会停在 0，下次启动才补结算（虽然会自动修，但白丢几十秒）。

## 配置：全部在窗口里，不用命令行

双击 `InfoCollect.exe` → 托盘图标 → 右键 → **打开配置界面**。分五段：

| 分区 | 能改什么 |
|---|---|
| 采集 | 采样间隔、闲置阈值、切换确认次数、是否采集窗口标题、标题截断长度、是否按标题切分会话 |
| 本机标识 | **显示名**，如「台式机」；多台电脑在手机上靠它区分。留空则用系统机器名 |
| 开机自启 | 勾选即写入注册表；下方会显示当前实际写入的命令，路径不对会给出黄色警告 |
| 上报到服务器 | 启用开关、**上报方式（自定义服务端 / Supabase）**、地址、Token、间隔、超时、关机推送、**立即推送**按钮 |
| 分类映射 | 每行 `进程名=分类`，可复制粘贴 |

顶部还有一行状态：`今日 1 小时 4 分（48 段）· 待上传 6 条 · 上次推送 3 分钟前`。
「上次推送」是新加的——没有它就没法确认云端到底同步没同步。

**首次运行**：配置文件还不存在时，双击 exe 会先弹配置窗口，保存后才进托盘。
这时「开机自启」默认已勾上（不勾的话关掉窗口就等于没装），仍然可以取消。

保存后不用重启：托盘进程 30 秒内发现 `config.json` 变化会自动热加载。

## 命令行（调试用，日常不需要）

在 `win\` 目录下：

```bash
py -3 -X utf8 app.py            # 等于 run，前台采集
py -3 -X utf8 app.py tray       # 托盘常驻（自启动用的就是它）
py -3 -X utf8 app.py stop       # 让托盘实例正常退出
py -3 -X utf8 app.py report      # 今日报表（有控制台打印，没有就开窗口）
py -3 -X utf8 app.py report --date 2026-10-30 --window
py -3 -X utf8 app.py ui         # 配置界面
py -3 -X utf8 app.py status     # 数据在哪、跑没跑、待上传几条
py -3 -X utf8 app.py autostart on|off|status
py -3 -X utf8 app.py device     # 看/改本机显示名（多设备区分用）
py -3 -X utf8 app.py cloud      # 云端配置与连通性自检
py -3 -X utf8 app.py upload     # 手动推一次待上传数据
py -3 -X utf8 app.py wipe --yes # 清空本地数据
```

`-X utf8` 不是可有可无：不加的话中文窗口标题在控制台会显示成乱码，容易误判成"API 取错了"。

## 代码地图

| 文件 | 职责 |
|---|---|
| `app.py` | 入口：argparse、单实例锁、日志、12 个子命令 |
| `winapi.py` | ctypes 封装：idle 时间、前台进程、标题、锁屏 |
| `sampler.py` | **核心**：采样状态机（粘滞切换、闲置回填、断档检测） |
| `store.py` | SQLite：建表、开/结会话、待上传队列 |
| `sanitize.py` | 标题截断、黑名单、工作单位归一化 |
| `classifier.py` | 进程名 → 分类（编码/浏览/沟通…） |
| `reporter.py` | 报表数据与文本排版 |
| `uploader.py` | 上报：`generic`（自建服务端）与 `supabase`（PostgREST RPC → `push_sessions` 函数）两种协议 |
| `autostart.py` | 开机自启；有 exe 就优先用 exe，没有才退回 pythonw + app.py |
| `make_version_info.py` | 生成 PyInstaller 的 Windows 版本资源（版本号读 `config.APP_VERSION`） |
| `tray.py` / `icon.py` | 托盘（纯 ctypes Shell_NotifyIcon）/ 纯 Python 生成 .ico |
| `ui_common.py` / `ui_config.py` / `ui_report.py` | tkinter 界面 |
| `shutdown.py` | 控制台形态下捕获关机/注销 |

## 打包成 exe

双击 `build_exe.bat`，产物在 `dist\InfoCollect\`（约 30MB，首次约 15 秒）。

先装一次 PyInstaller（只有打包需要，程序本身零依赖）：

```bash
py -3 -m pip install pyinstaller
```

打包脚本会先运行 `make_version_info.py` 生成 `version_info.txt`，版本号来自
`config.APP_VERSION`。打包完成后，右键 exe → 属性 → 详细信息 能看到
`0.3.0.0` 与产品名；托盘菜单底部也会显示版本。

用 `--onedir` 不用 `--onefile`：onefile 每次启动都要自解压到临时目录，慢 1~3 秒，还容易被杀软误报。

交付目录会一并拷入 6 个 bat：`start_silent` / `stop` / `config_ui` / `report` /
`install_autostart` / `uninstall_autostart`。其中 `report.bat` 会检测同目录的 exe，
用窗口模式打开报表（v0.3 修复）。

## 开机自启

`install_autostart.bat`，或 `app.py autostart on`。默认写的是**打包好的 exe**：

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Run\InfoCollect
= "…\win\dist\InfoCollect\InfoCollect.exe" tray
```

为什么要优先 exe：源码形态会写成

```
= "…\pythonw.exe" "…\win\app.py" tray
```

这把某个 Python 解释器的绝对路径钉死了 —— 那个 Python 一升级、卸载、或者 venv 被删，
开机就静默不启动，而且没有任何报错。exe 自带解释器，与本机环境彻底解耦。

找不到 exe（还没打包）时才退回 pythonw 形态。想让自启跑源码（改代码调试时）：

```bash
py -3 -X utf8 app.py autostart on --python
```

仅当前用户，不需要管理员。卸载就是删掉那一行。

**目录搬过家就要重装一次**，否则注册表还指向旧路径，失败是静默的
（`app.py autostart status` 会告诉你当前值、应写值和路径是否还能找到）。

打包版直接在新目录执行：

```powershell
.\InfoCollect.exe autostart on
```

**v0.3 启动体检**：托盘启动时会检查注册表——路径失效或与当前位置不一致时，
日志会写 `开机自启体检：...` 并弹出托盘通知，菜单项变成
「开机自启：路径已失效，点此修复」，点一下即重写为当前 exe 路径。

## 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 托盘没图标 | Win10/11 默认把新图标折叠进 `^` 溢出区，拖出来即可 |
| 时长比实际多 | 检查 `idle_threshold_seconds`（默认 300 秒），或看日志有没有断档 |
| 报错说已有实例 | 单实例锁生效了，先 `stop` 再启动 |
| 开机后没数据 | 先看 `%APPDATA%\InfoCollect\infocollect.log` 最后几行，再 `app.py autostart status` |
| exe 属性里版本不对 | 改了代码但没重新打包；改 `config.APP_VERSION` 后重跑 `build_exe.bat` |
