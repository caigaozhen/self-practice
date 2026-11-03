#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_report.py —— 报表窗口

为什么需要一个窗口版的报表：
    打包成 --windowed 的 exe 之后没有控制台，`report` 命令打印出来的东西
    根本没地方显示。所以托盘里的"查看报表"和 exe 的 report 都走这里。

用 Treeview 而不是把文本塞进 Text 控件：文本报表靠 `f"{x:<26}"` 对齐，
中文是双宽字符，等宽字体下照样会错位；用表格控件则天然对齐。
"""

from __future__ import annotations

import sys
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import ttk

import config
import reporter
import ui_common
from store import Store

WEEKDAYS = "一二三四五六日"


class ReportWindow:
    def __init__(self, day: date | None = None) -> None:
        self.day = day or date.today()
        self.store = Store(config.db_path())

        self.root = tk.Tk()
        self.root.title("InfoCollect · 时间去向")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        ui_common.enable_dpi()
        ui_common.style(self.root)
        ui_common.center(self.root, 780, 620, 620, 420)
        ui_common.set_window_icon(self.root)
        self._build()
        self._reload()
        self.root.bind("<Escape>", lambda e: self._on_close())
        self.root.bind("<Left>", lambda e: self._shift(-1))
        self.root.bind("<Right>", lambda e: self._shift(1))
        ui_common.bring_to_front(self.root)

    # ------------------------------------------------------------ 构建

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        # ---- 顶部：日期导航
        bar = ttk.Frame(outer)
        bar.pack(fill="x")
        ttk.Button(bar, text="◀", width=3, command=lambda: self._shift(-1)).pack(side="left")
        self.lbl_date = ttk.Label(bar, text="", style="Title.TLabel")
        self.lbl_date.pack(side="left", padx=10)
        ttk.Button(bar, text="▶", width=3, command=lambda: self._shift(1)).pack(side="left")
        ttk.Button(bar, text="今天", command=self._today).pack(side="left", padx=10)
        ttk.Button(bar, text="复制文本报表", command=self._copy_text).pack(side="right")

        # ---- 概要
        self.lbl_sum = ttk.Label(outer, text="", style="Head.TLabel")
        self.lbl_sum.pack(fill="x", pady=(8, 6))

        # ---- 三个标签页
        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True)
        self.tv_cat = self._make_tree(
            nb, "分类", [("分类", 130, "w"), ("时长", 110, "e"), ("占比", 70, "e"), ("", 220, "w")],
        )
        self.tv_app = self._make_tree(
            nb, "程序", [("程序", 260, "w"), ("时长", 110, "e"), ("占比", 70, "e"), ("", 200, "w")],
        )
        self.tv_detail = self._make_tree(
            nb, "明细",
            [("时间", 160, "w"), ("时长", 90, "e"), ("程序", 190, "w"),
             ("分类", 90, "w"), ("窗口标题", 320, "w")],
        )

        # ---- 底部状态
        self.lbl_foot = ttk.Label(outer, text="", style="Hint.TLabel")
        self.lbl_foot.pack(fill="x", pady=(6, 0))

    def _make_tree(self, nb: ttk.Notebook, title: str, columns) -> ttk.Treeview:
        frame = ttk.Frame(nb, padding=4)
        nb.add(frame, text=title)
        tv = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings",
                          selectmode="browse")
        for name, width, anchor in columns:
            tv.heading(name, text=name)
            tv.column(name, width=width, anchor=anchor, stretch=(name == columns[-1][0]))
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        tv.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        return tv

    # ------------------------------------------------------------ 数据

    def _shift(self, days: int) -> None:
        self.day += timedelta(days=days)
        self._reload()

    def _today(self) -> None:
        self.day = date.today()
        self._reload()

    def _clear(self, tv: ttk.Treeview) -> None:
        tv.delete(*tv.get_children())

    def _reload(self) -> None:
        d = self.day
        self.lbl_date.config(text=f"{d.strftime('%Y-%m-%d')}（周{WEEKDAYS[d.weekday()]}）")
        self._clear(self.tv_cat)
        self._clear(self.tv_app)
        self._clear(self.tv_detail)

        data = reporter.collect(self.store, d)
        total = data["total"]

        if total <= 0:
            self.lbl_sum.config(text="这一天没有记录")
            self.lbl_foot.config(
                text=f"数据文件：{self.store.path}　　（程序没运行过，或者数据被清空了）"
            )
            return

        self.lbl_sum.config(
            text=f"活跃总时长 {reporter.fmt_duration(total)}　·　{len(data['rows'])} 段会话"
        )

        for cat, sec in sorted(data["by_category"].items(), key=lambda x: -x[1]):
            ratio = sec / total
            self.tv_cat.insert("", "end", values=(
                cat, reporter.fmt_duration(sec), f"{ratio * 100:.1f}%",
                "█" * max(1, int(round(ratio * 24))),
            ))

        for app, sec in sorted(data["by_app"].items(), key=lambda x: -x[1])[:20]:
            ratio = sec / total
            self.tv_app.insert("", "end", values=(
                app, reporter.fmt_duration(sec), f"{ratio * 100:.1f}%",
                "█" * max(1, int(round(ratio * 18))),
            ))

        for row in data["rows"]:
            t0 = datetime.fromtimestamp(row["start"]).strftime("%H:%M:%S")
            t1 = datetime.fromtimestamp(row["end"]).strftime("%H:%M:%S")
            self.tv_detail.insert("", "end", values=(
                f"{t0} → {t1}", reporter.fmt_duration(row["seconds"]),
                row["app"], row["category"], row["title"],
            ))
        if self.tv_detail.get_children():
            self.tv_detail.yview_moveto(1.0)          # 明细默认滚到最新

        self.lbl_foot.config(
            text=f"数据文件：{self.store.path}　　← → 切换日期，Esc 关闭"
        )

    def _copy_text(self) -> None:
        text = reporter.render(self.store, self.day)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.lbl_foot.config(text="文本报表已复制到剪贴板")

    # ------------------------------------------------------------ 生命周期

    def _on_close(self) -> None:
        try:
            self.store.close()
        finally:
            self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def show(day: date | None = None) -> int:
    if not config.db_path().exists():
        root = tk.Tk()
        root.withdraw()
        from tkinter import messagebox
        messagebox.showinfo("InfoCollect", f"还没有数据文件：\n{config.db_path()}\n\n先启动采集再来看。")
        root.destroy()
        return 1
    return ReportWindow(day).run()


if __name__ == "__main__":
    if sys.stdout:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    arg = None
    if len(sys.argv) > 1:
        try:
            arg = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        except ValueError:
            arg = None
    sys.exit(show(arg))
