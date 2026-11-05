# V0.1 · 最简 tkinter：打开窗口，显示一段文字

> 40 行代码，打开一个窗口，贴一段 JSON 文本，并且能打包成 exe 双击运行。

不采集、不保存。唯一目的是**把 tkinter 的骨架立起来**，给后面每一版一个能跑的地基。

---

## 一、四个概念

```
Tk（窗口）→ Label（控件）→ pack（布局）→ mainloop（循环）
```

| tkinter | Java Swing | 干什么 |
|---|---|---|
| `tk.Tk()` | `new JFrame()` | 造窗口容器 |
| `tk.Label(...)` | `new JLabel(...)` | 造显示文字的控件 |
| `.pack()` | `setLayout()` + `add()` | 把控件挂到窗口上并定位 |
| `root.mainloop()` | EDT 事件分发线程 | 进入循环，窗口开始响应 |

**最关键的一条**：`mainloop()` 是**阻塞调用**，会占住主线程直到窗口关闭，所以必须是最后一行。

---

## 二、40 行代码的六个部分

| 编号 | 内容 | 作用 |
|---|---|---|
| 1 | `records = [...]` | 数据：一个列表两个字典，**写死的** |
| 2 | `json.dumps(...)` | Python 对象 → JSON 文本 |
| 3 | `tk.Tk()` + `title` + `geometry` | 造窗口，设标题与初始尺寸 |
| 4 | `tk.Label(...)` | 造标签。`justify="left"` 多行左对齐，`anchor="nw"` 贴左上角 |
| 5 | `label.pack(...)` | 放进窗口。`fill="both"` + `expand=True` 撑满 |
| 6 | `root.mainloop()` | 开始循环，窗口出现 |

两个容易困惑的点：

- **`tk.Label(root, ...)` 里的 `root`**：控件的父容器，相当于 Java 的 `frame.add(label)` 的 `frame`。不给它，tkinter 不知道画在哪个窗口里。
- **造完控件为什么还要 `pack()`**：造控件只是"内存里有个对象"，`pack()` 才把它挂到界面上。没 pack 的控件不会显示。

---

## 三、运行与打包

```bash
cd F:/self-practice/windows/tkinter-tool/V0.1
py -3 app.py          # 560×320 窗口，里面是两行 JSON
双击 build.bat        # → dist/TkDemo.exe
```

打包参数（与代码无关）：`--noconsole` 不弹黑框，`--onefile` 单文件，`--name TkDemo` 定产物名。

---

## 四、验收

- [x] `py -3 app.py` 弹出窗口，里面有 JSON 文本
- [x] 关窗后命令行正常返回，无报错堆栈
- [x] `build.bat` 产出 exe，双击能打开

---

## 五、这一版明显不够用的地方

| 问题 | 何时解决 |
|---|---|
| 数据写死，跟本机无关 | **V0.2** |
| 没有按钮，用户无法交互 | V0.2（加刷新按钮） |
| 文本不能选中复制 | 后续考虑换 `Text` |
| 不支持 `--selftest`，exe 无法自动验证 | V0.2 起支持 |

V0.1 的代码原样保留，没加 `--selftest`，所以它的 exe 只能**手动双击 + 手动关窗**验证。

---

## 六、下一版只加两件事

1. 数据改成**现场采集**（系统 / CPU / 内存 / 磁盘）
2. 加一个**刷新按钮**

界面结构、显示方式、打包方式都不动。
