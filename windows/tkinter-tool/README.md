# TimeLog · 今日时间记录器

一个 tkinter 写的小工具：输入「现在在做什么」，点一下记一条，数据存本地 JSON，已经打包成 exe，双击就能用。

**当前状态**：✅ 可运行、✅ 可打包（2026-11-04）

---

## 目录里有什么

```
tkinter-tool/
├── app.py          程序本体（约 180 行）
├── build.bat       双击即可重新打包
├── dist/
│   └── TimeLog.exe 打包产物，13MB，双击运行
├── build/          PyInstaller 中间文件（可删，每次打包重新生成）
├── TimeLog.spec    打包配置（自动生成，可删，重新打包会再生成）
└── .gitignore
```

**数据不在项目目录里**，在：

```
C:\Users\<用户名>\AppData\Local\TimeLog\records.json
```

界面上的「打开数据文件夹」按钮会直接跳到那儿。

---

## 两种运行方式

```bash
# 方式一：源码跑（改代码后用这个，改完立刻见效）
cd F:/self-practice/windows/tkinter-tool
py -3 app.py

# 方式二：双击 dist/TimeLog.exe
# 不依赖 Python 环境，可以直接拷给别人
```

参数 `--selftest`：启动后 1.2 秒自动关闭。这是给自动化验证用的，平时不用。

---

## 怎么重新打包

**双击 `build.bat`** 就行。它做的事等于这两条命令：

```bash
rmdir /s /q build dist
py -3 -m PyInstaller --noconsole --onefile --name TimeLog app.py
```

改完 `app.py` 必须**重新打包**，exe 里冻结的是打包那一刻的代码。

### 三个参数各管什么

| 参数 | 作用 | 去掉会怎样 |
|---|---|---|
| `--onefile` | 打成单个 exe | 变成 `dist/TimeLog/` 一个文件夹，几十个 dll，拷走要整个文件夹 |
| `--noconsole` | 不弹黑框 | 双击后先出现一个黑色命令行窗口，等程序关掉才消失 |
| `--name TimeLog` | 产物名 | 默认叫 `app.exe`，容易和别的程序混淆 |

---

## 代码结构（四层）

```
数据层      load_records / save_records    读写 JSON
界面层      TimeLogApp.build_ui            搭控件树
交互层      add_record / delete_selected   按钮点下去干什么
入口        main                            建窗口 + mainloop
```

### 要懂的三件事

**一、tkinter 是「容器套控件」**

```
Tk（整个窗口）
└── Frame（一块横向条带）
    ├── Label（"现在在做什么？"）
    ├── Entry（输入框）
    └── Button（"记一条"）
```

`pack()` 决定谁挨着谁：`side="left"` 从左往右排，`side="right"` 从右往左排，`fill="x"` 表示横向拉满，`expand=True` 表示多余空间都给它。

**调换 `pack()` 的顺序，界面就变样**——这是 tkinter 布局唯一需要记住的规则。

**二、按钮有两种绑定方式**

```python
ttk.Button(top, text="记一条", command=self.add_record)   # 点击触发
self.entry.bind("<Return>", lambda e: self.add_record())  # 回车触发
```

注意 `command=self.add_record` **没有括号**——交出去的是函数本身，不是执行结果。这和 V0.3 里 `sys.excepthook = handle` 是同一个道理，只是这里藏在参数里更容易写错。

`bind` 的回调会收到一个 `event` 参数，所以要用 `lambda e:` 接住，否则参数个数对不上。

**三、界面只是壳，状态在 `self.records` 这个列表里**

```
点「记一条」→ self.records.append(...) → save_records() → refresh() 重画列表
点「删除选中」→ del self.records[i]  → save_records() → refresh() 重画列表
```

每次改完列表都**整份重写文件 + 整份重画**。数据量小的时候这是最不容易出错的写法——不用维护"界面和内存哪里不一致"。

---

## 打包时会踩的坑

| 坑 | 表现 | 原因 |
|---|---|---|
| 数据写在 exe 旁边 | 换台机器/放进 `Program Files` 就写不进去 | 程序目录可能只读，必须用 `%LOCALAPPDATA%` |
| 改了代码忘了重新打包 | 双击 exe 还是老界面 | exe 里是打包那一刻的副本 |
| 打包后窗口一闪就没 | 双击看不到任何东西 | 异常被吞了（`--noconsole` 没有 stderr）。调试方法：临时去掉 `--noconsole` 再打包，看命令行报什么 |
| 杀毒软件报警 | 提示"未知发布者" | 未签名 exe 的通病，自用忽略即可 |

第三条是这类程序最常见的失败方式，也是为什么 `--selftest` 这个参数有用：**它让 exe 能被自动化验证**，不用靠肉眼双击。

---

## 下一步可以加什么

按"先出成果、碰到问题再解决"的顺序，优先级从高到低：

1. **记录时长**：每条记录加一个"到这一条为止"的时长，状态栏显示今天总时长
2. **双击编辑**：现在只能删了重记
3. **按日期筛选**：一条 Combobox 选日期
4. **托盘图标**：关窗口不退出，缩到右下角（这就是 V0.5 想做的事，换个项目重来会顺手很多）
5. **导出 CSV**：`pandas` 或手写 `csv` 模块
