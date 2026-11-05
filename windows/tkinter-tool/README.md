# tkinter-tool · 桌面小工具（版本化练习）

用 tkinter 做一个 Windows 桌面小工具，按版本递进：**每版只加一个能力，每版都能运行、都能打包成 exe**。

原项目 `../manual-info-collect/`（注册表自启 + 采集时间）已封存，转到这条线上重新开始——先做出看得见的东西，再往里加复杂度。

---

## 版本路线

| 版本 | 增量 | 验收一句话 | 状态 |
|---|---|---|---|
| **V0.1** | 最简窗口：显示一段 JSON 文本 | 窗口能打开，能打包成 exe | ✅ 已完成 |
| **V0.2** | 采集硬件数据（psutil）+ 刷新按钮 | 窗口里显示 14 项本机真实数据，exe 可双击运行 | ✅ 已完成 |
| V0.3 | 静态/动态拆分 + `after` 定时刷新 | 数字每秒自己变，界面不卡 | ✅ 已完成 |
| V0.4 | 导出数据（CSV / JSON 落盘） | 点一下能把当前信息存成文件 | 待开始 |
| V0.5 | 托盘图标（关窗不退出） | 右下角有图标，右键能退出 | 待开始 |

**不做的**：开机自启、注册表、上传服务器。这些留在已封存的原项目里。

---

## 目录结构

```
tkinter-tool/
├── V0.1/
│   ├── app.py        40 行，打开窗口显示 JSON
│   ├── build.bat     打包 → dist/TkDemo.exe
│   └── README.md     这 40 行的逐段说明
├── V0.2/
│   ├── app.py        采集硬件信息并显示
│   ├── build.bat     打包 → dist/HardwareInfo.exe
│   ├── requirements.txt   psutil>=7.0.0
│   ├── dist/
│   │   └── HardwareInfo.exe   已打包，14MB，双击可运行
│   └── README.md     采集清单 + 4 个坑 + pack 实测规律
├── V0.3/
│   ├── app.py        静态只采一次，动态每秒刷新
│   ├── build.bat     打包 → dist/HardwareLive.exe
│   ├── requirements.txt   psutil>=7.0.0
│   └── README.md     静态/动态拆分 + after 三件事 + cpu_percent 两模式
└── README.md         本文件
```

**两个版本完全独立**，互不引用。想看 V0.1 就进 `V0.1/`，想跑新功能就进 `V0.2/`。

---

## 快速开始

```bash
# 跑某一版
cd F:/self-practice/windows/tkinter-tool/V0.2
py -3 app.py

# 首次运行前装依赖（只有 V0.2 需要，V0.1 无依赖）
py -3 -m pip install -r requirements.txt

# 自检（启动后 1.2 秒自动关闭，用于验证 exe 是否正常）
py -3 app.py --selftest

# 打包成 exe
双击 V0.2/build.bat   →  V0.2/dist/HardwareInfo.exe
```

---

## 关于 exe 打包

三参数固定用法：

```
py -3 -m PyInstaller --noconsole --onefile --name <产物名> app.py
```

| 参数 | 作用 | 去掉会怎样 |
|---|---|---|
| `--noconsole` | 不弹黑框 | 双击后先出现命令行窗口 |
| `--onefile` | 单个 exe | 变成几十个文件组成的文件夹 |
| `--name` | 产物名 | 默认叫 `app.exe` |

**改了 `app.py` 必须重新打包**，exe 里冻结的是打包那一刻的代码副本。

产物 `build/` 和 `*.spec` 是中间文件，可以随时删，重新打包会再生成。

---

## 依赖情况

| 版本 | 运行需要（第三方） | 打包需要 |
|---|---|---|
| V0.1 | **无** | PyInstaller |
| V0.2 | **`psutil`**（见 `V0.2/requirements.txt`） | PyInstaller + psutil |
| V0.3 | **`psutil`**（同版本，无新增依赖） | PyInstaller + psutil |

选择 psutil 的理由：它用几行代码换掉了原方案里近百行的 `ctypes` 结构体声明，还额外提供了物理核心数、CPU 使用率、开机时间这些标准库拿不到的数据。V0.2 的 README 里有两者行数对照。

这意味着：

- V0.1 不需要 `requirements.txt`，V0.2 需要
- 别人拿到 exe 都能直接用，不用装 Python 或 psutil（已经打包进去）
- 换一台机器改 V0.2 的代码，要先 `pip install -r requirements.txt`

---

## 学习原则

1. **先出成果，再讲原理**——每版先给能跑的东西和验证命令，概念等碰到问题了再解释
2. **一次只加一个概念**——V0.2 只加了"数据从写死变成采集"和"一个按钮"，没有同时引入定时器、进度条、多线程
3. **每版都能独立运行和打包**——不留下"跑不起来的中间状态"
4. **数字要能验证**——验收标准写成"窗口里显示真实数据"，而不是"看起来对"
