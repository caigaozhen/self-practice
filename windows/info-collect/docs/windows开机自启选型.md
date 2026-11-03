# Windows 开机自启：方案选型与当前实现

> 本文只讲**自启**这一件事：现在用的是什么、怎么做、怎么验证、出问题怎么修；以及 Windows 上还有哪些做法、为什么没选。
>
> 程序本身做什么、采集口径、数据流向见 `README.md` 与 `docs/detailed-design.md`；打包 exe 见 `docs/operations.md` §3。

---

## 一、当前在用什么

**注册表 `HKCU` 下的 `Run` 键，写一行「程序绝对路径 + 参数 `tray`」。**

```
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
    InfoCollect   (REG_SZ)   =   "F:\...\win\dist\InfoCollect\InfoCollect.exe" tray
```

| 项 | 值 |
|---|---|
| 根键 | `HKEY_CURRENT_USER`（当前用户，不是 HKLM） |
| 路径 | `Software\Microsoft\Windows\CurrentVersion\Run` |
| 值名 | `InfoCollect` |
| 值类型 | `REG_SZ`（普通字符串，不是 `REG_EXPAND_SZ`） |
| 值内容 | `"<程序路径>" tray` |
| 是否需要管理员 | **否** |
| 触发时机 | 该用户**登录进桌面之后**（不是内核开机时） |

源码形态写的是另一种内容，机制完全相同：

```
    InfoCollect   (REG_SZ)   =   "C:\...\Python314\pythonw.exe" "F:\...\win\app.py" tray
```

---

## 二、当前方案详解

### 2.1 原理

Windows 登录后会读取这个键，把里面每一条字符串当作命令行**逐条执行**。所以"安装自启"的本质就是**写一个字符串**，"卸载自启"就是**删掉它**。没有服务、没有守护进程、没有额外的系统组件。

整个机制的实现只有三个函数（`win/autostart.py`）：

```python
launcher_command()   # 拼出该写的那串命令
install()            # 写注册表值
uninstall()          # 删注册表值
```

### 2.2 写入策略：优先 exe，没有才退回源码

`launcher_command()` 的决策顺序：

| 条件 | 写入的内容 |
|---|---|
| 找到了打包好的 `InfoCollect.exe`（默认情形） | `"…\InfoCollect.exe" tray` |
| 没有 exe（还没打包） | `"…\pythonw.exe" "…\app.py" tray` |
| 显式加 `--python` | 强制写源码形态，调试改代码时用 |

搜索 exe 的两个位置：`win\InfoCollect.exe`、`win\dist\InfoCollect\InfoCollect.exe`。

**为什么优先 exe**：源码形态把某个 `pythonw.exe` 的绝对路径钉死了。那个 Python 一旦升级、卸载，或者 venv 被删，开机就静默不启动——而且没有任何报错。exe 自带解释器，与本机 Python 环境彻底解耦。

### 2.3 为什么不需要管理员

`HKEY_CURRENT_USER` 是**当前用户自己的**配置区，写它不触发 UAC。需要管理员的只有 `HKEY_LOCAL_MACHINE`（对本机所有用户生效）。

个人工具只给自己用，写 HKCU 就够了：

- 不弹 UAC，安装零打扰
- 采集的也是这个用户的窗口活动，语义一致
- 卸载就是删自己那一个值，不污染系统

### 2.4 两个容易出事的细节

**① 路径必须加引号。**
这串字符串被原样交给 `CreateProcess`。路径带空格却不加引号时，系统按空格切分：`"C:\Program Files\App\app.exe"` 会被理解成「运行 `C:\Program.exe`」。这既是功能 bug，也是真实的提权手法（Unquoted Service Path）。代码里两段路径都强制加引号。

**② 用 `pythonw.exe` 而不是 `python.exe`。**
前者是 GUI 子系统（PE Subsystem = 2），启动不分配控制台，不会闪黑框；后者会留一个黑窗口在那儿。

### 2.5 一个必须说清的概念偏差

名字叫「开机自启」，**实际是「登录后自启」**。

| | 触发时机 | 是否适用本程序 |
|---|---|---|
| 真正的"开机" | 内核启动完成，无人登录 | 不适用：没有前台窗口可记 |
| Run 键 / 启动文件夹 | 用户登录进桌面后 | **适用**，即当前做法 |
| 计划任务 `At startup` | 开机即触发，可无人登录 | 技术上可行，但跑在 Session 0（见 §四） |

对这个程序，"登录后"是**正确语义**而不是妥协：没人登录时也没有使用行为可统计。

---

## 三、操作步骤

以下命令都在 `F:\self-practice\windows\info-collect\win` 目录下执行（exe 形态把 `py -3 -X utf8 app.py` 换成 `InfoCollect.exe` 即可）。

### 步骤 A · 首次开启（图形界面，推荐日常使用）

1. 双击 `win\start_silent.bat`（或 `dist\InfoCollect\InfoCollect.exe`），右下角出现托盘图标。
   > Win10/11 默认把新图标折叠进 `^` 溢出区，点小箭头拖出来固定即可。
2. 右键托盘图标 → **打开配置界面**（也可直接双击 `win\config_ui.bat`）。
3. 找到 **「开机自启」** 区块，**勾选**复选框。
4. 点底部 **保存**。
5. 看该区块下方的灰字，应显示：

   ```
   当前已安装：
   "F:\...\win\dist\InfoCollect\InfoCollect.exe" tray
   ```

   若出现黄色提示「与当前程序位置不一致」或「其中某个路径已不存在」，取消勾选、再勾一次即可重写。

### 步骤 B · 命令行开启（部署、批量、修复用）

1. 打开终端，进入 `win` 目录：

   ```bash
   cd F:\self-practice\windows\info-collect\win
   ```

2. 执行：

   ```bash
   py -3 -X utf8 app.py autostart on
   ```

3. 预期输出：

   ```
   已开启开机自启（仅当前用户，无需管理员）：
     HKCU\Software\Microsoft\Windows\CurrentVersion\Run\InfoCollect
     = "F:\...\InfoCollect.exe" tray

   下次登录 Windows 时会自动以托盘方式启动。
   ```

   想强制用源码形态（改代码调试时）：

   ```bash
   py -3 -X utf8 app.py autostart on --python
   ```

### 步骤 C · 验证是否真的写进去了（三种方式，任选）

**方式一：程序自检（推荐，能同时看到"应写值"和"实际值"）**

```bash
py -3 -X utf8 app.py autostart status
```

预期：

```
运行形态：源码 + 解释器
打包产物：F:\...\dist\InfoCollect\InfoCollect.exe
状态：已启用
应写命令："F:\...\InfoCollect.exe" tray
当前命令："F:\...\InfoCollect.exe" tray
```

三者关系：`当前命令` 与 `应写命令` **完全一致** = 正常。不一致会打出警告行。

**方式二：直接读注册表**

```bash
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v InfoCollect
```

预期：

```
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
    InfoCollect    REG_SZ    "F:\...\InfoCollect.exe" tray
```

**方式三：确认路径真实存在**

把上面命令里的路径复制出来，去掉引号后：

```bash
dir "F:\self-practice\windows\info-collect\win\dist\InfoCollect\InfoCollect.exe"
```

**方式四：看任务管理器**
`Ctrl+Shift+Esc` → **「启动」选项卡** → 找到 `InfoCollect`，状态应为「已启用」。若显示「已禁用」，右键启用即可（Windows 把禁用状态单独记在 `Explorer\StartupApproved\Run` 里，不删原值）。

### 步骤 D · 关闭自启

```bash
py -3 -X utf8 app.py autostart off
```

或手动删值：

```bash
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v InfoCollect /f
```

图形界面对应：配置界面取消勾选「开机自启」→ 保存。

> 关闭自启**不会**退出正在运行的程序，只是下次登录不再自动拉起。

### 步骤 E · 移动了程序目录之后（必须做）

自启存的是**绝对路径**，目录一改就指向不存在的文件，开机静默失败。

1. 把程序目录整体移到新位置（整个文件夹一起移，不要只移 exe）。
2. 在新位置重新写一次自启：

   ```bash
   cd <新路径>\win
   py -3 -X utf8 app.py autostart on
   ```

   或双击新位置里的 `install_autostart.bat`。

3. 再跑一次 `app.py autostart status`，确认 `当前命令` 已经指向新路径。

> 忘记这一步的表现是：下次开机没有图标、也没有任何报错，只有 `infocollect.log` 的最后心跳停在前一天。

### 步骤 F · 勾了自启但开机没启动（排查清单）

按顺序检查，前两条能覆盖 90% 的情况：

1. **任务管理器「启动」页被禁用？** 见步骤 C 方式四。
2. **注册表里的路径还在吗？** 见步骤 C 方式三；不存在 → 执行步骤 E。
3. **安全软件拦了？** 部分安全软件会清理 Run 键项或提示用户放行，检查有没有被隔离/拦截记录。
4. **配置与注册表不一致？** 配置里 `"autostart": true` 但注册表没有值。程序启动时会弹「开机自启未生效」通知；执行 `autostart on` 重写。
5. **程序自己有异常？** 看日志末尾：

   ```bash
   tail -20 "%APPDATA%\InfoCollect\infocollect.log"
   ```

   正常启动会有「托盘模式启动，上报状态：…」「采样启动：…」两行。

---

## 四、其他可选方案（以及为什么没选）

### 4.1 启动文件夹（Startup Folder）

把程序本体或快捷方式放进：

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup      ← 当前用户
%ProgramData%\Microsoft\Windows\Start Menu\Programs\Startup  ← 所有用户（需管理员）
```

- **本质**：与 Run 键同一套启动流程，只是载体从注册表值换成文件。
- **优点**：可视化，用户能在资源管理器里直接看到、拖走。
- **缺点**：想带启动参数（`tray`）就得建 `.lnk` 快捷方式，纯 Python 下要走 COM（`IShellLink` / `WScript.Shell`），比 `winreg` 十行代码重得多。
- **没选的原因**：功能等价但实现更重，且"目录里多一个文件"比"注册表一个值"更难解释。

### 4.2 任务计划程序（Task Scheduler）

```bash
schtasks /create /tn InfoCollect /tr "路径 tray" /sc onlogon /rl limited /f
```

支持的能力比 Run 键丰富：

- 触发器：`onlogon` / `onstart` / `onidle` / 定时
- 延迟启动：`/delay 00:00:30`，避开登录瞬间的资源争抢
- 失败重试、以最高权限运行、仅在交流电源时运行

- **优点**：功能最全，是 Run 键的"超集"。
- **缺点**：任务定义是 XML，创建/修改/排查都更啰嗦；卸载要删任务；对个人小工具属于过度设计。
- **关键限制**：勾选"不管用户是否登录都运行"后跑在 **Session 0**，与桌面隔离，画不出托盘图标。
- **没选的原因**：当前需求不需要延迟、重试、提权；用不到的能力不该付复杂度成本。

### 4.3 Windows 服务

```powershell
sc create InfoCollect binPath= "路径" start= auto
```

- **优点**：开机即启动、崩溃可自动重启、不依赖用户登录。
- **致命限制**：自 Vista 起服务运行在 **Session 0**，与交互式桌面完全隔离，**无法显示托盘图标、无法弹窗**（能画，但用户看不见）。
- **其他代价**：安装需管理员；调试要 `sc query` / 事件查看器；卸载要 `sc delete`。
- **没选的原因**：本程序的交互入口就是通知区图标和右键菜单，服务形态直接把这个入口砍掉了。这是**技术形态上的不可行**，不是偏好问题。

### 4.4 RunOnce

`HKCU\...\RunOnce`，格式与 Run 键相同，但**执行后 Windows 自动删除该值**，只跑一次。

- 用途是"安装程序重启后收尾"。
- 不适合常驻程序：第二次开机就没了。

### 4.5 组策略登录脚本

`计算机配置 / 用户配置 → Windows 设置 → 脚本（登录/启动）`，由域控统一下发。只在**加入域的企业环境**有意义；普通个人电脑（尤其家庭版）连 `gpedit.msc` 都没有。不适用。

### 4.6 MSIX / UWP 的 StartupTask

在 `Package.appxmanifest` 声明 `windows.startupTask`，由系统托管。只对打包成 MSIX 的应用有效。本程序是普通 exe / Python 脚本，不适用。

### 4.7 横向对比

| 方案 | 需管理员 | 触发时机 | 能出托盘 | 延迟启动 | 失败重试 | 任务管理器可禁用 | 实现复杂度 | 卸载方式 |
|---|---|---|---|---|---|---|---|---|
| **HKCU Run 键（当前）** | 否 | 登录后 | 能 | 否 | 否 | 是 | 极低 | 删一个值 |
| 启动文件夹 | 否 | 登录后 | 能 | 否 | 否 | 是 | 低（建 .lnk） | 删一个文件 |
| 计划任务 `onlogon` | 否 | 登录后 | 能 | 是 | 是 | 否 | 中 | 删一个任务 |
| 计划任务 `onstart` | 是 | 开机（可无人登录） | **不能** | 是 | 是 | 否 | 中高 | 删一个任务 |
| Windows 服务 | 是 | 开机 | **不能** | 是 | 是 | 否 | 高 | `sc delete` |
| RunOnce | 否 | 登录后**一次** | 能 | 否 | 否 | — | 极低 | 自动删除 |
| 组策略登录脚本 | 域控 | 登录/开机 | 视脚本 | 是 | 视配置 | 否 | 高 | 改策略 |
| MSIX StartupTask | — | 登录后 | 能 | 是 | 是 | 是 | 高（需打包） | 卸载应用 |

---

## 五、为什么最终选 Run 键

### 5.1 四条决定性理由

**① 零权限，不打扰用户。**
写 `HKCU` 不触发 UAC。服务、`HKLM`、`onstart` 任务都要提权——为一个记录时间的小工具每次安装弹 UAC，很多人会直接放弃。

**② 技术形态决定：托盘程序必须活在用户会话里。**
服务和"无人登录也运行"的任务跑在 Session 0，与桌面隔离，画不出图标。这条硬约束直接排除了 §4.3 与 §4.2 的一半用法。

**③ 实现成本最低，且完全可解释。**
`winreg` 十行代码，读写删都能用 `reg query` 手工验证。相比之下，计划任务要生成/解析 XML，服务要处理 SCM 交互——对"自己用"的工具，这是明显的过度设计。

**④ 可精确自检，故障不靠猜。**
因为格式是自己定的字符串，程序能算出"应写值"，再与实际值逐字比对，直接判断三种异常：值不存在、路径已失效（`stale`）、指向旧位置。任务计划和服务做不到这么直白。

### 5.2 三条已知代价（如实记录）

| 代价 | 影响 | 当前应对 |
|---|---|---|
| **登录后才启动**，非开机即启动 | 从开机到登录这段时间不记录 | 无人登录时也没有前台窗口可记，无实际损失 |
| **可能被禁用**：任务管理器「启动」页可关，安全软件可能提示 | 用户以为开着、其实没起 | 启动时体检 + `autostart status` 比对实际值 |
| **无失败重试**：一次没起来就是没起来 | 可能第二天才发现没数据 | 日志"最后心跳"可反查；值是静态字符串，本身不易失败 |

### 5.3 什么时候该换成任务计划

需求变了就别硬扛：

- 需要**真正的开机即启动**（无人登录也跑）→ `onstart` + `/delay`
- 需要**失败重试**或崩溃拉起 → 计划任务（服务亦可，但要接受无界面）
- 需要**管理员权限** → 计划任务 + `/rl highest`
- 需要**错峰启动**避免拖慢登录 → `/delay 00:00:30`

迁移成本很低：只改 `autostart.py` 的 `launcher_command()` 与 `install()` / `uninstall()` 三个函数，其余模块不感知。

---

## 六、为什么自启失败是"静默"的

这是本方案最需要警惕的一点。

`pythonw.exe` 和 `--windowed` 打包的 exe **没有控制台**，`stdout` / `stderr` 无处可去。于是：

- 路径写错、文件被移动 → 系统尝试启动、失败、**不提示任何东西**
- Python 抛异常 → 异常信息无人接收，进程直接消失
- 注册表被安全软件清掉 → 下次开机就是没启动

**故障往往要等到第二天看报表"昨天一片空白"才暴露。**

三层防线：

1. **启动时体检**（`app.py` 的 `autostart_warning()`）：读注册表实际值与期望值，不一致就弹托盘通知，菜单里同时出现「开机自启：路径已失效，点此修复」，点一下重写。
2. **日志最后心跳**：`infocollect.log` 记录每次启动与心跳，`app.py status` 会换算成"21 秒前"，一眼看出程序是否活着。
3. **目录搬家必重装**：见步骤 E。

---

## 七、速查

```bash
# 开启 / 关闭 / 查看
py -3 -X utf8 app.py autostart on
py -3 -X utf8 app.py autostart off
py -3 -X utf8 app.py autostart status

# 强制写源码形态（调试用）
py -3 -X utf8 app.py autostart on --python

# 直接查 / 删注册表
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v InfoCollect
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v InfoCollect /f

# 看日志
tail -20 "%APPDATA%\InfoCollect\infocollect.log"
```

| 场景 | 做哪一步 |
|---|---|
| 第一次装 | 步骤 A |
| 部署到新机器 / 批量 | 步骤 B |
| 确认有没有生效 | 步骤 C |
| 不想要自启了 | 步骤 D |
| 移动了目录 | 步骤 E |
| 开机没启动 | 步骤 F |

相关文档：`docs/operations.md` §5（部署视角的操作手册）、`docs/detailed-design.md`（模块与状态机）。
