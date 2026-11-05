"""最简版 tkinter：打开窗口，直接显示一段 JSON。

只需要看懂四件事：
    窗口 Tk  →  控件 Label  →  布局 pack  →  循环 mainloop
"""

import json
import tkinter as tk

# 1. 数据：Python 的「列表 + 字典」
records = [
    {"time": "2026-11-04 10:30:00", "text": "学习 tkinter"},
    {"time": "2026-11-04 10:45:00", "text": "看懂 class"},
]

# 2. 变成 JSON 文本，也就是 records.json 文件里存的样子
text = json.dumps(records, ensure_ascii=False, indent=2)

# 3. 造窗口（root 就是那个窗口）
# 这个tk.Tk()类似于实例化一个窗口对象
root = tk.Tk()
root.title("最简 tkinter")
root.geometry("560x320")

# 4. 造控件：一个标签，把 JSON 文本贴上去
# 这里类似于创建一个div,但是没有指明详细位置,只有内容
label = tk.Label(
    root,
    text=text,
    justify="left",          # 多行文字左对齐
    anchor="nw",             # 文字的位置：左上角
    font=("Consolas", 11),
)

# 5. 把控件放进窗口，并让它撑满、留出边距
# 这里类似于把这个div的详细位置,占用给定了下来
label.pack(fill="both", expand=True, padx=12, pady=12)

# 6. 进入事件循环：窗口开始显示、开始响应
root.mainloop()
