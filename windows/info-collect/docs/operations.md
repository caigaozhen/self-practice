# InfoCollect 部署与运维手册

> 文档定位：面向「现在就要把它装起来 / 用起来 / 出问题了怎么查」的操作步骤。
> 需求见 [requirements.md](requirements.md)，设计见 [design.md](design.md) 与
> [detailed-design.md](detailed-design.md)，数据见 [database-design.md](database-design.md)。
>
> 当前版本：**v0.3**（2026-11-02）

---

## 1. 交付物与目录

```
info-collect/
├── win/                          Windows 采集端源码
│   └── dist/InfoCollect/         打包产物 = 交付物（整个目录拷走）
├── mobile/                       手机查看端（uni-app）
├── supabase/                     云端建表脚本 + 说明
├── dev/                          本地测试工具（不交付）
└── docs/                         文档
```

打包后 `dist\InfoCollect\` 的内容：

| 文件 | 用途 |
|---|---|
| `InfoCollect.exe` | 主程序（双击 = 托盘常驻） |
| `_internal\` | Python 运行时与依赖，必须和 exe 一起存在 |
| `infocollect.ico` | 图标 |
| `start_silent.bat` | 启动托盘（等价双击 exe） |
| `stop.bat` | 正常退出（结算当前会话 + 尝试推送） |
| `config_ui.bat` | 打开配置界面 |
| `report.bat` | 打开报表窗口（v0.3 起支持 exe 形态） |
| `install_autostart.bat` | 开启开机自启 |
| `uninstall_autostart.bat` | 关闭开机自启 |

运行数据不在程序目录，而在 `%APPDATA%\InfoCollect\`：

| 文件 | 内容 |
|---|---|
| `config.json` | 配置 |
| `infocollect.db` | 全部会话（SQLite，可用 DB Browser 打开） |
| `infocollect.log` | 运行日志（轮转，2MB × 3） |

---

## 2. 环境准备

| 场景 | 需要 |
|---|---|
| 只运行打包版 | Windows 10 / 11；不需要 Python |
| 从源码运行 | Python 3.10+（开发机用 3.14） |
| 重新打包 | Python + `py -3 -m pip install pyinstaller` |
| 手机端 | Node ≥ 18（Vite 5 要求）；APK 用 HBuilderX 云打包 |
| 云端（可选） | 一个 Supabase 项目 |

---

## 3. 构建 exe

### 3.1 步骤

```powershell
# 1. 安装打包工具（仅首次，程序运行本身零依赖）
py -3 -m pip install pyinstaller

# 2. 进入 win 目录
cd F:\self-practice\windows\info-collect\win

# 3. 双击 build_exe.bat，或在 PowerShell 里直接跑 PyInstaller
.\build_exe.bat
```

`build_exe.bat` 做三件事：

1. `make_version_info.py` 读取 `config.APP_VERSION`，生成 `version_info.txt`；
2. PyInstaller 以 `--onedir --windowed --version-file` 打包；
3. 把 6 个 bat 入口拷进 `dist\InfoCollect\`。

产物约 30MB，首次构建约 15 秒。

### 3.2 版本号

- 唯一来源：`win/config.py` 的 `APP_VERSION`。
- exe 文件属性（右键 → 属性 → 详细信息）显示 `文件版本 0.3.0.0`、
  产品名 `InfoCollect`、描述 `InfoCollect 时间去向记录器`。
- `app.py status` 和托盘菜单底部也显示版本。

改版本号的流程：

```text
改 config.APP_VERSION → 重新执行 build_exe.bat → 检查 exe 属性
```

不要手改 `version_info.txt`（它由脚本生成）。

### 3.3 构建验证

```powershell
# 版本资源
$v = (Get-Item .\dist\InfoCollect\InfoCollect.exe).VersionInfo
"$($v.FileVersion) | $($v.ProductName) | $($v.FileDescription)"

# 交付目录完整
Get-ChildItem .\dist\InfoCollect | Select-Object Name
```

期望：`FileVersion=0.3.0.0`，目录里有 6 个 bat 和 exe。

---

## 4. 首次部署

### 4.1 放到一个稳定位置

推荐把整个 `dist\InfoCollect\` 放到不会随手移动的位置，例如：

```text
C:\Users\<你>\AppData\Local\Programs\InfoCollect\
```

原因：开机自启写的是**绝对路径**。目录一移动，注册表就指向不存在的文件，
而且失败是静默的（详见 §5.5）。

### 4.2 首次启动

双击 `InfoCollect.exe`：

1. 第一次运行（`%APPDATA%\InfoCollect\config.json` 不存在）会先弹配置窗口；
2. 配置窗口默认勾选「登录 Windows 时自动启动」；
3. 保存后写入配置与注册表，程序进入托盘；
4. 右下角出现图标（Win10/11 默认可能折叠进 `^` 溢出区）。

> 首次运行不勾自启也可以，但关掉配置窗口后程序仍在托盘运行；下次开机不会自动启动。

### 4.3 立刻确认在采集

右键托盘 → 「查看今日报表」应能看到数据；或：

```powershell
.\InfoCollect.exe status
Get-Content "$env:APPDATA\InfoCollect\infocollect.log" -Tail 10
```

`status` 会打印版本、数据文件、最后心跳、今日活跃时长。

---

## 5. 开机自启（重点）

### 5.1 目前的实现方式

**写入位置**（仅当前用户，不需要管理员）：

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
  InfoCollect = "<命令>" tray
```

**命令有两种形态**，由 `win/autostart.py` 的 `launcher_command()` 决定：

| 形态 | 注册表里的值 | 何时使用 |
|---|---|---|
| 打包 exe（默认优先） | `"C:\...\InfoCollect.exe" tray` | 找到 exe 时 |
| 源码 + 解释器 | `"C:\...\pythonw.exe" "F:\...\app.py" tray` | 没找到 exe 时 |

为什么优先 exe：源码形态把某个 `pythonw.exe` 的绝对路径钉死，Python 升级、卸载、
venv 删除后开机会静默不启动；exe 自带解释器，与本机 Python 环境解耦。

**开机后的执行路径**：

```text
Windows 登录
  → 读取 HKCU\...\Run 的 InfoCollect 值
  → 启动 "<exe 路径>" tray
  → app.py 解析到 cmd_tray
  → 单实例锁 → 加载配置 → 启动采样线程 → 创建托盘图标
  → 每 5 秒采样，持续写入本地 SQLite
```

**相关代码位置**：

| 能力 | 函数 |
|---|---|
| 判断是否打包 | `autostart.is_frozen()` |
| 找 exe | `autostart.packaged_exe()`（当前 exe / `dist\InfoCollect\InfoCollect.exe`） |
| 生成命令 | `autostart.launcher_command(mode)` |
| 写/删注册表 | `autostart.install()` / `uninstall()` / `set_enabled()` |
| 诊断 | `autostart.diagnose()`（`enabled` / `command` / `expected` / `stale`） |
| 启动体检（v0.3） | `app.py` 的 `autostart_warning()` + `Tray.on_start` |
| 一键修复（v0.3） | 托盘菜单「开机自启：路径已失效，点此修复」→ `repair_autostart()` |

### 5.2 三种开启方式

| 方式 | 操作 | 适用 |
|---|---|---|
| 配置界面 | `config_ui.bat` → 勾选「登录 Windows 时自动启动」→ 保存 | 日常 |
| 托盘菜单 | 右键托盘 →「开机自启」 | 临时开关 |
| 命令行 / bat | `install_autostart.bat`，或 `InfoCollect.exe autostart on` | 部署、修复 |

源码形态：

```powershell
cd win
py -3 -X utf8 app.py autostart on
```

强制用源码形态（改代码调试时）：

```powershell
py -3 -X utf8 app.py autostart on --python
```

### 5.3 验证

```powershell
# 方式一：程序自检（推荐，能看出应写值与实际值）
cd win
py -3 -X utf8 app.py autostart status

# 方式二：直接读注册表
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name InfoCollect |
    Select-Object -ExpandProperty InfoCollect

# 方式三：确认路径真实存在
Test-Path 'C:\...\InfoCollect.exe'
```

`autostart status` 正常输出示例：

```text
运行形态：打包 exe
打包产物：C:\...\InfoCollect.exe
状态：已启用
应写命令："C:\...\InfoCollect.exe" tray
当前命令："C:\...\InfoCollect.exe" tray
```

若出现「路径已不存在」或「与当前程序位置不一致」，执行一次
`InfoCollect.exe autostart on` 即可重写。

### 5.4 移动目录 / 升级后必须做的事

**只要 exe 的绝对路径变了**，就要重写自启：

```powershell
# 在新位置执行（打包版）
.\InfoCollect.exe autostart on

# 或双击新位置的 install_autostart.bat
```

源码模式：

```powershell
cd 新位置的 win
py -3 -X utf8 app.py autostart on
```

v0.3 起，程序启动时会自动体检并弹通知，托盘菜单会变成
「开机自启：路径已失效，点此修复」，点一下即可修复。

### 5.5 为什么自启失败是「静默」的

- `pythonw.exe` 和 `--windowed` 的 exe 没有控制台，启动失败没有任何弹窗或输出；
- Windows 也不会提示「某个启动项失败了」；
- 结果就是：第二天打开报表才发现没有数据。

发现办法：

1. 看日志最后几行：`%APPDATA%\InfoCollect\infocollect.log`；
2. 看最后心跳：`InfoCollect.exe status` 会显示几十秒前 / 几小时前 / 未运行；
3. 看注册表：`autostart status` 的 `stale` 字段；
4. v0.3 启动体检：托盘通知 + 日志 `开机自启体检：...`。

### 5.6 关闭 / 移除自启

```powershell
.\InfoCollect.exe autostart off
# 或双击 uninstall_autostart.bat
```

只删除 `HKCU\...\Run` 下的 `InfoCollect` 值，不碰其它启动项、不删程序、不删数据。

---

## 6. 日常操作

### 6.1 托盘菜单

| 菜单项 | 作用 |
|---|---|
| 今日活跃：x 小时 x 分（n 段） | 只读状态 |
| 待上传：n 条 / 已同步 | 只读状态 |
| 查看今日报表 | 打开报表窗口（分类 / 程序 / 明细） |
| 打开配置界面 | 采集、本机标识、自启、上报、分类映射 |
| 立即推送 | 手动推一次待上传数据 |
| 暂停采集 | 结算当前会话，之后只写心跳；再点恢复 |
| 开机自启 / 路径失效修复 | 开关或修复启动项 |
| 打开数据目录 | 打开 `%APPDATA%\InfoCollect\` |
| InfoCollect v0.3 | 只读版本 |
| 退出 | 正常收尾（结算 + 尝试推送） |

左键双击图标 = 查看今日报表；左键单击 = 刷新提示。

### 6.2 常用命令

```powershell
cd F:\self-practice\windows\info-collect\win

py -3 -X utf8 app.py status
py -3 -X utf8 app.py report
py -3 -X utf8 app.py report --date 2026-10-30 --window
py -3 -X utf8 app.py ui
py -3 -X utf8 app.py stop
py -3 -X utf8 app.py cloud --ping
py -3 -X utf8 app.py cloud --dry-run
py -3 -X utf8 app.py upload --dry-run
py -3 -X utf8 app.py device --label 台式机
py -3 -X utf8 app.py wipe --yes
```

打包版对应命令（无控制台输出，靠退出码和日志判断）：

```powershell
.\InfoCollect.exe autostart status
.\InfoCollect.exe stop
.\InfoCollect.exe upload
```

`-X utf8` 不是可有可无：不加时中文标题在控制台会显示成乱码。

### 6.3 启动与退出

| 动作 | 推荐方式 | 说明 |
|---|---|---|
| 启动 | 双击 `start_silent.bat` / `InfoCollect.exe` | 无窗口，托盘常驻 |
| 调试启动 | `start.bat` / `app.py run` | 有黑窗口，Ctrl+C 停止 |
| 正常退出 | 托盘「退出」/ `stop.bat` / `stop` 子命令 | 结算当前会话并尝试推送 |
| 不推荐 | 任务管理器强杀 | 当前会话 `end_ts` 残留为 0，下次启动补结算 |

---

## 7. 升级

### 7.1 同路径覆盖（最常见）

```text
1. 托盘右键 → 退出（或 stop.bat）
2. 用新构建的 dist\InfoCollect\ 覆盖旧目录
3. 双击 InfoCollect.exe
4. 检查 .\InfoCollect.exe autostart status（路径没变，通常无需重写）
```

数据在 `%APPDATA%`，覆盖程序目录不会影响数据与配置。

### 7.2 换路径

```text
1. 退出旧实例
2. 把新目录放到新位置
3. 在新位置执行 .\InfoCollect.exe autostart on
4. 删除旧目录（可选，先确认新版本正常）
```

### 7.3 升级检查清单

- [ ] `InfoCollect.exe` 文件属性版本正确
- [ ] 托盘图标出现，菜单底部版本正确
- [ ] `status` 最后心跳在 2 分钟内
- [ ] `autostart status` 的当前命令与应写命令一致
- [ ] 报表能看到今天的数据
- [ ] 日志无「未捕获异常」

---

## 8. 卸载

```text
1. 托盘右键 → 退出
2. 关闭自启：uninstall_autostart.bat / InfoCollect.exe autostart off
3. 删除程序目录（dist\InfoCollect 或你复制到的位置）
4. 如不再需要数据：删除 %APPDATA%\InfoCollect\
```

卸载不写系统其它位置；注册表只涉及 `HKCU\...\Run\InfoCollect` 一个值。

---

## 9. 数据备份、迁移与清空

### 9.1 备份

推荐先退出采集，再复制整个目录：

```powershell
.\InfoCollect.exe stop
Copy-Item "$env:APPDATA\InfoCollect" "D:\backup\InfoCollect-$(Get-Date -Format yyyyMMdd)" -Recurse
```

SQLite 使用 WAL 模式，运行中直接复制可能漏掉 `-wal` 中尚未合并的数据；
要么先停止程序，要么使用 SQLite backup API。

### 9.2 迁移到另一台电脑

```text
1. 新电脑安装/复制程序目录
2. 复制 %APPDATA%\InfoCollect\ 过去（保留历史数据与 device_id）
3. 新电脑执行 InfoCollect.exe autostart on（注册表路径是绝对的）
4. 如需区分设备，配置界面改「显示名」
```

### 9.3 清空

```powershell
py -3 -X utf8 app.py wipe --yes
```

只删 `sessions` 表，保留 `meta`（含 `device_id`）和配置。云端数据需在 Supabase
Dashboard 手动删除（未开放删除接口）。

---

## 10. 手机端与云端（可选）

完整步骤见 [`supabase/README.md`](../supabase/README.md) 与 [`mobile/README.md`](../mobile/README.md)。摘要：

```text
1. Supabase Dashboard → SQL Editor → 粘贴 supabase/schema.sql → Run
2. Authentication → 创建一个登录用户（手机端用邮箱密码登录）
3. Windows 配置界面 → 上报：启用、方式 Supabase、地址填项目根、Token 填 anon key
4. py -3 -X utf8 app.py cloud --ping 验证
5. 手机打开 H5/APK → 填地址、anon key、邮箱、密码 → 查看
```

权限底线：anon 只 insert、authenticated 只 select、谁都没有 update/delete；
上报必须走 `push_sessions` 函数。

---

## 11. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 托盘没有图标 | Win11 折叠进 `^` 溢出区 | 点任务栏 `^`，把图标拖出来 |
| 开机后没有数据 | 自启路径失效 / 注册表没写 | `autostart status`；重跑 `autostart on`；看日志最后心跳 |
| 提示「已经在运行」 | 单实例锁生效 | 找托盘图标；或 `stop` 后再启动 |
| 时长明显偏多 | 闲置阈值太大 / 被强杀残留 / 全屏视频误判 | 调小 `idle_threshold_seconds`；正常退出；观察日志断档 |
| 控制台中文乱码 | 未加 UTF-8 选项 | 命令加 `-X utf8`；日志本身是 UTF-8 |
| 配置界面打不开 | 源码形态的解释器缺 tkinter | 用打包版；或换带 tkinter 的 Python |
| 推送失败 | 地址/密钥/RLS/网络 | `cloud --ping`；按提示查函数、权限、地址 |
| 推送成功但手机看不到 | 手机未登录 / 无 SELECT 权限 / 时区 | 检查 authenticated 的 select 授权与登录用户 |
| exe 被报毒 | PyInstaller 打包产物常见误报 | 用 `--onedir`（已采用）；添加排除项 |
| 双击 exe 没反应 | 首次运行弹配置窗被其它窗口挡住 | 看任务栏；或用 `config_ui.bat` |
| 版本号不一致 | 忘记重新打包 / 改了 `version_info.txt` | 改 `config.APP_VERSION` 后重跑 `build_exe.bat` |
| 目录移动后自启失效 | 注册表存的是旧绝对路径 | 新位置执行 `autostart on`，或用托盘「修复」 |

日志位置：`%APPDATA%\InfoCollect\infocollect.log`。
排障顺序：**先看日志最后 20 行 → 再看 `status` 的心跳 → 再看 `autostart status`**。

---

## 12. 运维检查清单

### 部署后

- [ ] exe 能双击启动，托盘图标存在
- [ ] `status` 显示版本、数据文件、最后心跳
- [ ] 报表能看到今天的会话
- [ ] 配置界面可打开并保存
- [ ] `autostart status` 当前命令 = 应写命令，路径存在
- [ ] 重启电脑后自动出现托盘图标（真实验收项）

### 每月

- [ ] 数据量正常（一天 200~800 段，没有单条 > 3 小时的异常会话）
- [ ] 日志没有持续 warning / exception
- [ ] 若启用上报，`待上传` 不持续增长
- [ ] 备份一次 `%APPDATA%\InfoCollect\`

### 发版前

- [ ] `py -3 -m py_compile win\*.py`
- [ ] `node dev\test_format.mjs`
- [ ] `build_exe.bat` 产物版本正确
- [ ] 文档中的版本号与 `config.APP_VERSION` 一致
