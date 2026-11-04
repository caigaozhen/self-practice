"""TimeLog · 今日时间记录器（tkinter 版）。

一个能自己用的小工具：输入「现在在做什么」，点一下记一条，
数据存成本地 JSON。下一步打包成 exe，双击就能开。
"""

import ctypes
import json
import os
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

APP_NAME = "TimeLog"

# 数据放用户目录，不要在 exe 旁边写文件（Program Files 是只读的）
DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / APP_NAME
DATA_FILE = DATA_DIR / "records.json"


# ------------------------------------------------------------------ 数据


def load_records() -> list[dict]:
    """读全部记录，文件不存在或内容坏了都返回空列表。"""
    if not DATA_FILE.exists():
        return []
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_records(records: list[dict]) -> None:
    """整份覆盖写回。目录不存在就先建。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ 界面


class TimeLogApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.records = load_records()

        root.title("TimeLog · 今日记录")
        root.geometry("600x440")
        root.minsize(480, 320)

        self.build_ui()
        self.refresh()

    def build_ui(self) -> None:
        # --- 顶部：输入 + 按钮 ---
        top = ttk.Frame(self.root, padding=(12, 12, 12, 6))
        top.pack(fill="x")

        ttk.Label(top, text="现在在做什么？").pack(side="left")
        self.entry = ttk.Entry(top)
        self.entry.pack(side="left", fill="x", expand=True, padx=8)
        self.entry.bind("<Return>", lambda event: self.add_record())
        ttk.Button(top, text="记一条", command=self.add_record).pack(side="left")

        # --- 中间：记录列表 ---
        mid = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        mid.pack(fill="both", expand=True)

        self.listbox = tk.Listbox(mid, font=("微软雅黑", 10), activestyle="none")
        scroll = ttk.Scrollbar(mid, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # --- 底部：状态栏 + 次要按钮 ---
        bottom = ttk.Frame(self.root, padding=(12, 6, 12, 12))
        bottom.pack(fill="x")

        self.status = ttk.Label(bottom, text="")
        self.status.pack(side="left")

        ttk.Button(bottom, text="删除选中", command=self.delete_selected).pack(side="right")
        ttk.Button(bottom, text="打开数据文件夹", command=self.open_data_dir).pack(
            side="right", padx=6
        )

    # --- 交互 ---

    def add_record(self) -> None:
        text = self.entry.get().strip()
        if not text:
            self.status.configure(text="内容不能为空")
            return

        self.records.append(
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "text": text}
        )
        save_records(self.records)
        self.entry.delete(0, "end")
        self.refresh()
        self.listbox.see("end")

    def delete_selected(self) -> None:
        selected = self.listbox.curselection()
        if not selected:
            self.status.configure(text="先在列表里选中一条")
            return

        index = selected[0]
        del self.records[index]
        save_records(self.records)
        self.refresh()

    def open_data_dir(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(DATA_DIR)  # 只有 Windows 有

    # --- 刷新 ---

    def refresh(self) -> None:
        self.listbox.delete(0, "end")
        today = datetime.now().strftime("%Y-%m-%d")

        for record in self.records:
            self.listbox.insert("end", f"{record['time']}   {record['text']}")

        today_count = sum(1 for r in self.records if r["time"].startswith(today))
        self.status.configure(text=f"共 {len(self.records)} 条 · 今天 {today_count} 条")


# ------------------------------------------------------------------ 入口


def main() -> int:
    # 高分屏下让文字不发虚
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    TimeLogApp(root)

    if "--selftest" in sys.argv:
        root.after(1200, root.destroy)  # 自动关闭，用于打包后验证能起来

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
