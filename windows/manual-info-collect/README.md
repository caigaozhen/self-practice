# manual-info-collect · 手写版学习路线

从零手写一个「开机自启 + 采集 Windows 使用时间」的程序，目的是**理解每个零件**，而不是尽快得到成品。

正式版在 `windows/info-collect/`，已经能跑。这里重写一遍：**不看现成代码先写，写完再对照**，差异才是学习内容。

---

## 怎么用这套目录

1. 进 `V0.1/`，读它的 `README.md`
2. 自己写代码，跑通，按文末「验收标准」逐条自测
3. 过了再进下一个版本
4. 卡住超过 30 分钟再回来看正式版对应文件（每份 README 里都写了"参考文件"）

**不要跳版本。** 每一版都只加一个能力，跳着做会把问题叠在一起，出了 bug 分不清是哪一层。

---

## 版本路线

| 版本 | 增量 | 为什么排在这个位置 | 验收一句话 |
|---|---|---|---|
| **V0.1** | 写一个注册表 Run 键，重登后拉起自己 | 地基：先证明"自启"这件事能成 | 重登后日志多一行带时间戳的记录 |
| **V0.2** | 幂等、自动挑解释器、`status` 失效检测 | 把自启做扎实：能装、能卸、能验 | 反复 install/uninstall 不出错，`status` 能指出"路径已失效" |
| **V0.3** | 日志文件 + 全局异常兜底 | 无控制台程序，没有日志等于瞎 | 故意抛异常，日志里能看到完整 traceback |
| **V0.4** | 单实例锁（`CreateMutexW`） | 自启 + 手动双击会撞车，同段时间记两遍 | 第二次启动被拦住并给出提示 |
| **V0.5** | 托盘图标 + 右键菜单（`Shell_NotifyIconW`） | 有了交互入口，才叫"程序" | 通知区出现图标，右键能退出，图标能正常消失 |
| **V0.6** | 采集前台窗口（`GetForegroundWindow` + `GetLastInputInfo`） | 开始产生真正的数据 | 日志里出现"进程名 + 时长"，人离开时停止计时 |
| **V0.7** | 会话切分 + SQLite 落库 | 有了数据流才需要存储 | 一天的记录能按应用汇总出总时长 |
| **V0.8** | 配置界面 + 上报（可选） | 打磨与扩展 | 界面上改参数生效；数据能推到一个 HTTP 端点 |

---

## 每一版都会练到的"通用能力"

| 版本 | 顺带学会的 |
|---|---|
| V0.1 | `winreg` 五个 API、`REG_SZ`、路径引号、`pythonw` 与 `python` 的区别 |
| V0.2 | 幂等设计、异常分类（"本来就没有"不算错误）、自检式 CLI |
| V0.3 | `logging` 轮转、`sys.excepthook`、无控制台程序的调试方法 |
| V0.4 | Win32 内核对象、命名对象、`GetLastError` 的用法 |
| V0.5 | ctypes 结构体、窗口消息循环、`WM_` 消息、explorer 重启后重加图标 |
| V0.6 | 跨进程取信息（`OpenProcess` + `QueryFullProcessImageNameW`）、UWP 穿透 |
| V0.7 | 状态机、SQLite WAL、时间区间切分、"未结算会话"的容错 |
| V0.8 | tkinter 布局与线程边界、HTTP 上报与幂等 |

---

## 与正式版的对应关系

| 版本 | 正式版里的参考文件 |
|---|---|
| V0.1 / V0.2 | `win/autostart.py`（约 220 行，整个自启就这么多） |
| V0.3 | `win/app.py` 的 `setup_logging()` / `install_excepthook()` |
| V0.4 | `win/app.py` 的 `acquire_single_instance()` |
| V0.5 | `win/tray.py` + `win/icon.py` |
| V0.6 | `win/winapi.py` + `win/sampler.py` |
| V0.7 | `win/store.py` + `win/sampler.py` 的会话结算 |
| V0.8 | `win/ui_config.py` + `win/uploader.py` |

---

## 环境约定

- Windows 10 / 11
- Python 3.10+
- **只用标准库**：`winreg`、`ctypes`、`sqlite3`、`tkinter`、`logging`、`json`、`urllib`
- 建议直接用 `py -3` 运行，不要一开始就搞 venv（先把功能跑通）

---

## 一个提醒

每版的 README 都写了「验收标准」。**验收不过就不要进下一版**——这些标准是刻意设计成"能自动判真假"的，比如"重登后日志多一行"，不会骗自己。
