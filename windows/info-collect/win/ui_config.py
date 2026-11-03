#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_config.py —— 配置窗口（tkinter）

设计原则：
    ① 只改配置，不改代码逻辑。保存后立即写 config.json，托盘进程 30 秒内
       发现文件变了会自动热更新，不用重启。
    ② 校验放在保存前，报错要指到具体哪一项，不能只说"配置有误"。
    ③ 分类映射用"进程名=分类"的纯文本编辑，比一堆动态控件好用——
       这是每天都要改的东西，能复制粘贴最重要。
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

import autostart
import config
import reporter
import ui_common
from store import Store
from uploader import Uploader

# 上报方式：config.json 里存英文，界面上显示中文。
# 少一个下划线就会变成两处硬编码字符串对不上，所以提成常量。
PROVIDER_GENERIC = "generic"
PROVIDER_SUPABASE = "supabase"
PROVIDER_GENERIC_UI = "自定义服务端"
PROVIDER_SUPABASE_UI = "Supabase（手机端用这个）"


def _ago(ts: int) -> str:
    """时间戳 → 「3 分钟前」。0 或负数一律当"没有记录"。"""
    import time as _time

    d = int(_time.time()) - int(ts)
    if d < 0:
        return "刚刚"
    if d < 60:
        return "刚刚"
    if d < 3600:
        return f"{d // 60} 分钟前"
    if d < 86400:
        return f"{d // 3600} 小时前"
    return f"{d // 86400} 天前"


class ConfigWindow:
    def __init__(self, first_run: bool = False) -> None:
        self.first_run = first_run
        self.cfg = config.load()
        self.root = tk.Tk()
        self.root.title("InfoCollect 配置")
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)
        ui_common.enable_dpi()
        ui_common.style(self.root)
        # 高一点，让「上报方式」不用滚动就能看到；960 是 1080p 屏幕上的安全值
        ui_common.center(self.root, 680, 880, 620, 480)
        ui_common.set_window_icon(self.root)

        self.vars: dict[str, tk.Variable] = {}
        self._build()
        self._load_into_form()
        ui_common.bring_to_front(self.root)

    # ------------------------------------------------------------ 小工具

    def _scroll_area(self, parent) -> ttk.Frame:
        """带滚轮的滚动区域。字段多，小屏幕上不加这个会看不到底部按钮。"""
        canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(2, 2, 10, 2))
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(window, width=e.width))

        def wheel(event):
            delta = -1 if event.delta > 0 else 1
            canvas.yview_scroll(delta * 3, "units")

        # 只在指针进入区域时接管滚轮，避免影响别处
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return inner

    def _section(self, parent, title: str) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text=title, padding=8)
        lf.pack(fill="x", pady=(0, 10))
        lf.columnconfigure(1, weight=1)
        return lf

    def _int_entry(self, parent, row: int, key: str, label: str, hint: str = "", width=10):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        var = tk.StringVar()
        self.vars[key] = var
        ttk.Entry(parent, textvariable=var, width=width).grid(
            row=row, column=1, sticky="w", padx=(10, 10), pady=3)
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
                row=row, column=2, sticky="w")
        return var

    def _str_entry(self, parent, row: int, key: str, label: str, hint: str = "", show=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        var = tk.StringVar()
        self.vars[key] = var
        e = ttk.Entry(parent, textvariable=var, show=show)
        e.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=3)
        if hint:
            e.bind("<FocusIn>", lambda ev: None)
            ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
                row=row + 1, column=1, columnspan=2, sticky="w", padx=(10, 0))
        return var

    def _check(self, parent, row: int, key: str, label: str, hint: str = ""):
        var = tk.BooleanVar()
        self.vars[key] = var
        ttk.Checkbutton(parent, text=label, variable=var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=3)
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
                row=row + 1, column=0, columnspan=3, sticky="w", padx=(22, 0))
        return var

    # ------------------------------------------------------------ 构建

    def _build(self) -> None:
        head = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        head.pack(fill="x")
        ttk.Label(head, text="采集与上报设置", style="Title.TLabel").pack(side="left")
        self.lbl_status = ttk.Label(head, text="", style="Hint.TLabel")
        self.lbl_status.pack(side="right")

        body = ttk.Frame(self.root, padding=(12, 8, 6, 0))
        body.pack(fill="both", expand=True)
        form = self._scroll_area(body)

        # ---- 采集
        s = self._section(form, "采集")
        self._int_entry(s, 0, "sample_interval_seconds", "采样间隔（秒）",
                        "越小越准，越大越省电。默认 5")
        self._int_entry(s, 1, "idle_threshold_seconds", "闲置阈值（秒）",
                        "超过这么久没碰键鼠 = 离开了。默认 300（5 分钟）")
        self._int_entry(s, 2, "switch_confirm_samples", "切换确认次数",
                        "新程序连续出现几次才认定切换。默认 3，用于消除碎片")
        self._check(s, 3, "collect_window_title", "采集窗口标题",
                    "关掉后只能统计到程序名，统计精度会下降（标题可能含敏感内容）")
        self._int_entry(s, 5, "title_max_length", "标题截断长度",
                        "默认 120 字符，防止超长标题撑大数据库")
        self._check(s, 6, "split_by_title", "按标题首段切分会话",
                    "例如 \"a.py - PyCharm\" 和 \"b.py - PyCharm\" 算两段工作")

        # ---- 本机标识
        s = self._section(form, "本机标识（多台电脑时用来区分）")
        self._str_entry(s, 0, "device_label", "显示名",
                        "如「台式机」「笔记本」。留空则用系统机器名；手机端按它筛选")

        # ---- 自启
        s = self._section(form, "开机自启")
        self._check(s, 0, "autostart_enabled", "登录 Windows 时自动启动（不需要管理员）")
        self.lbl_auto = ttk.Label(s, text="", style="Hint.TLabel", wraplength=600,
                                  justify="left")
        self.lbl_auto.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # ---- 上报
        s = self._section(form, "上报到服务器（可选）")
        self._check(s, 0, "upload_enabled", "启用上报",
                    "关掉时数据只留在本机，功能完全不影响")

        ttk.Label(s, text="上报方式").grid(row=2, column=0, sticky="w", pady=3)
        self.vars["upload_provider_ui"] = tk.StringVar()
        self.cbo_provider = ttk.Combobox(
            s, textvariable=self.vars["upload_provider_ui"], state="readonly",
            values=[PROVIDER_GENERIC_UI, PROVIDER_SUPABASE_UI], width=18)
        self.cbo_provider.grid(row=2, column=1, sticky="w", padx=(10, 10), pady=3)
        self.cbo_provider.bind("<<ComboboxSelected>>", lambda e: self._sync_provider_hint())

        ttk.Label(s, text="地址").grid(row=3, column=0, sticky="w", pady=3)
        v_ep = tk.StringVar()
        self.vars["upload_endpoint"] = v_ep
        ttk.Entry(s, textvariable=v_ep).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=3)

        ttk.Label(s, text="Token").grid(row=4, column=0, sticky="w", pady=3)
        v_tk = tk.StringVar()
        self.vars["upload_token"] = v_tk
        ttk.Entry(s, textvariable=v_tk, show="•").grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=3)

        self.lbl_provider = ttk.Label(s, text="", style="Hint.TLabel",
                                      wraplength=620, justify="left")
        self.lbl_provider.grid(row=5, column=0, columnspan=3, sticky="w", pady=(2, 4))

        self._int_entry(s, 6, "upload_interval_hours", "推送间隔（小时）", "默认 4")
        self._int_entry(s, 7, "upload_timeout_seconds", "超时（秒）", "默认 10，跨境访问别低于 5")
        self._check(s, 8, "upload_on_shutdown", "关机时最后推一次",
                    "只能尽力而为：Windows 关机只给几秒，超时的数据靠下次启动补传")

        row = ttk.Frame(s)
        row.grid(row=11, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(row, text="立即推送", command=self._test_upload).pack(side="left")
        self.lbl_test = ttk.Label(row, text="", style="Hint.TLabel")
        self.lbl_test.pack(side="left", padx=10)

        # ---- 分类（放最后：日常几乎不改，但占了半屏）
        s = self._section(form, "分类映射")
        ttk.Label(s, text="每行一条，格式：进程名=分类（进程名写任务管理器里看到的那个）",
                  style="Hint.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        self.txt_cat = tk.Text(s, height=8, wrap="none", font=("Consolas", 9))
        self.txt_cat.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        s.columnconfigure(0, weight=1)

        # ---- 底部按钮
        foot = ttk.Frame(self.root, padding=(12, 6, 12, 12))
        foot.pack(fill="x")
        ttk.Button(foot, text="保存", command=self._save).pack(side="right")
        ttk.Button(foot, text="取消", command=self._cancel).pack(side="right", padx=8)
        ttk.Button(foot, text="恢复默认值", command=self._reset).pack(side="left")
        ttk.Button(foot, text="打开数据目录", command=self._open_dir).pack(side="left", padx=8)

    # ------------------------------------------------------------ 载入 / 保存

    def _load_into_form(self) -> None:
        c = self.cfg
        self.vars["sample_interval_seconds"].set(str(c["sample_interval_seconds"]))
        self.vars["idle_threshold_seconds"].set(str(c["idle_threshold_seconds"]))
        self.vars["switch_confirm_samples"].set(str(c["switch_confirm_samples"]))
        self.vars["collect_window_title"].set(bool(c["collect_window_title"]))
        self.vars["title_max_length"].set(str(c["title_max_length"]))
        self.vars["split_by_title"].set(bool(c["split_by_title"]))

        u = c.get("upload") or {}
        self.vars["upload_enabled"].set(bool(u.get("enabled")))
        self.vars["upload_endpoint"].set(str(u.get("endpoint") or ""))
        self.vars["upload_token"].set(str(u.get("token") or ""))
        self.vars["upload_interval_hours"].set(str(u.get("interval_hours", 4)))
        self.vars["upload_timeout_seconds"].set(str(u.get("timeout_seconds", 10)))
        self.vars["upload_on_shutdown"].set(bool(u.get("on_shutdown", True)))

        self.vars["device_label"].set(str(c.get("device_label") or ""))
        prov = str(u.get("provider") or PROVIDER_GENERIC)
        self.vars["upload_provider_ui"].set(
            PROVIDER_SUPABASE_UI if prov == PROVIDER_SUPABASE else PROVIDER_GENERIC_UI)
        self._sync_provider_hint()

        self.txt_cat.delete("1.0", "end")
        for app, cat in sorted((c.get("category_map") or {}).items()):
            self.txt_cat.insert("end", f"{app}={cat}\n")

        # 首次运行默认勾上自启：这个程序的价值就是"开机后一直在记"，
        # 不勾的话用户关掉窗口就等于没装。仍然可以取消。
        self.vars["autostart_enabled"].set(
            True if self.first_run else autostart.is_enabled())
        self._refresh_status()

    def _refresh_status(self) -> None:
        bits = []
        if config.db_path().exists():
            try:
                st = Store(config.db_path())
                try:
                    data = reporter.collect(st, date.today())
                    bits.append(f"今日 {reporter.fmt_duration(data['total'])}"
                                f"（{len(data['rows'])} 段）")
                    pending = st.pending_count()
                    bits.append(f"待上传 {pending} 条" if pending else "无待上传")
                    last = 0
                    try:
                        last = int(st.get_meta("last_upload_at", "0") or 0)
                    except ValueError:
                        last = 0
                    if last:
                        bits.append(f"上次推送 {_ago(last)}")
                finally:
                    st.close()
            except Exception:
                pass
        self.lbl_status.config(text="　·　".join(bits) if bits else "还没有采集数据")

        info = autostart.diagnose()
        if info["enabled"]:
            msg = f"当前已安装：\n{info['command']}"
            if info["stale"]:
                msg += "\n⚠ 其中某个路径已不存在，自启会静默失败。取消再勾选一次可修复。"
            elif info["command"] != info["expected"]:
                msg += f"\n⚠ 与当前程序位置不一致，建议取消再勾选一次。\n当前应写：{info['expected']}"
        else:
            msg = f"当前未安装。勾选后写入：\n{info['expected']}"
        self.lbl_auto.config(text=msg)

    def _sync_provider_hint(self) -> None:
        """两种上报方式的地址/Token 含义完全不同，必须跟着下拉框变。"""
        if self.vars["upload_provider_ui"].get() == PROVIDER_SUPABASE_UI:
            self.lbl_provider.config(text=(
                "Supabase：地址只填项目根地址，如 https://xxxx.supabase.co"
                "（程序自动补 /rest/v1/rpc/push_sessions，写到数据库函数）；"
                "Token 填 anon public key。"
                "手机端要用另一个账号密码登录，见 mobile/README.md。"))
        else:
            self.lbl_provider.config(text=(
                "自建服务端：地址填完整接口，如 https://example.com/api/sessions；"
                "Token 会放进请求头 Authorization: Bearer。"))

    def _parse_category(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self.txt_cat.get("1.0", "end").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
            elif "\t" in line:
                k, v = line.split("\t", 1)
            else:
                continue
            k, v = k.strip().lower(), v.strip()
            if k and v:
                out[k] = v
        return out

    def _validate(self) -> list[str]:
        errs: list[str] = []

        def as_int(key, label, lo, hi):
            raw = str(self.vars[key].get()).strip()
            try:
                n = int(float(raw))
            except ValueError:
                errs.append(f"{label}：请填整数，现在是「{raw}」")
                return None
            if not (lo <= n <= hi):
                errs.append(f"{label}：应在 {lo} ~ {hi} 之间")
                return None
            return n

        as_int("sample_interval_seconds", "采样间隔", 1, 3600)
        as_int("idle_threshold_seconds", "闲置阈值", 30, 86400)
        as_int("switch_confirm_samples", "切换确认次数", 1, 20)
        as_int("title_max_length", "标题截断长度", 20, 500)
        as_int("upload_timeout_seconds", "上报超时", 1, 60)

        try:
            h = float(str(self.vars["upload_interval_hours"].get()).strip())
            if h <= 0:
                errs.append("推送间隔：必须大于 0")
        except ValueError:
            errs.append("推送间隔：请填数字（小时，可以是小数）")

        if self.vars["upload_enabled"].get():
            ep = str(self.vars["upload_endpoint"].get()).strip()
            if not ep.startswith(("http://", "https://")):
                errs.append("接口地址：启用上报时必须填 http:// 或 https:// 开头的地址")

        return errs

    def _collect(self) -> dict:
        cfg = dict(self.cfg)          # 保留未知字段，便于向下兼容
        cfg["sample_interval_seconds"] = int(float(self.vars["sample_interval_seconds"].get()))
        cfg["idle_threshold_seconds"] = int(float(self.vars["idle_threshold_seconds"].get()))
        cfg["switch_confirm_samples"] = int(float(self.vars["switch_confirm_samples"].get()))
        cfg["collect_window_title"] = bool(self.vars["collect_window_title"].get())
        cfg["title_max_length"] = int(float(self.vars["title_max_length"].get()))
        cfg["split_by_title"] = bool(self.vars["split_by_title"].get())
        cfg["category_map"] = self._parse_category()
        cfg["device_label"] = str(self.vars["device_label"].get()).strip()[:40]

        up = dict(cfg.get("upload") or {})
        up["enabled"] = bool(self.vars["upload_enabled"].get())
        up["provider"] = (
            PROVIDER_SUPABASE
            if self.vars["upload_provider_ui"].get() == PROVIDER_SUPABASE_UI
            else PROVIDER_GENERIC
        )
        up["endpoint"] = str(self.vars["upload_endpoint"].get()).strip()
        up["token"] = str(self.vars["upload_token"].get()).strip()
        up["interval_hours"] = float(self.vars["upload_interval_hours"].get())
        up["timeout_seconds"] = int(float(self.vars["upload_timeout_seconds"].get()))
        up["on_shutdown"] = bool(self.vars["upload_on_shutdown"].get())
        cfg["upload"] = up

        cfg["autostart"] = bool(self.vars["autostart_enabled"].get())
        return cfg

    def _save(self) -> None:
        errs = self._validate()
        if errs:
            messagebox.showerror("配置有误", "\n\n".join(errs), parent=self.root)
            return

        cfg = self._collect()
        try:
            config.save(cfg)
        except Exception as e:
            messagebox.showerror("保存失败", f"{type(e).__name__}: {e}", parent=self.root)
            return

        # 显示名有两处消费者：config.json（上报 payload 用）和数据库 meta
        # （status / 本地报表用）。只写一处就会出现"改了但手机上看不到"。
        try:
            st = Store(config.db_path())
            try:
                st.set_device_label(cfg.get("device_label") or "")
            finally:
                st.close()
        except Exception:
            pass

        # 自启按勾选状态落地
        want = bool(self.vars["autostart_enabled"].get())
        if want != autostart.is_enabled():
            ok, msg = autostart.set_enabled(want)
            if not ok:
                messagebox.showwarning("自启设置失败", msg, parent=self.root)

        self.cfg = cfg
        messagebox.showinfo(
            "已保存",
            "配置已写入：\n"
            f"{config.config_path()}\n\n"
            "正在运行的采集程序会在 30 秒内自动读取新配置，不用重启。",
            parent=self.root,
        )
        self.root.destroy()

    def _reset(self) -> None:
        if not messagebox.askyesno("恢复默认", "把表单恢复成默认值？\n（还没保存，需要再点「保存」）",
                                   parent=self.root):
            return
        self.cfg = dict(config.DEFAULTS)
        self._load_into_form()

    def _cancel(self) -> None:
        self.root.destroy()

    def _open_dir(self) -> None:
        import os
        config.ensure_dir()
        os.startfile(str(config.app_dir()))

    # ------------------------------------------------------------ 测试推送

    def _test_upload(self) -> None:
        errs = self._validate()
        if errs:
            messagebox.showerror("配置有误", "\n\n".join(errs), parent=self.root)
            return
        cfg = self._collect()
        if not cfg["upload"]["enabled"]:
            self.lbl_test.config(text="上报没启用，先勾上「启用上报」")
            return

        self.lbl_test.config(text="正在推送…")

        def work():
            n, text = 0, ""
            try:
                st = Store(config.db_path())
                try:
                    before = st.pending_count()
                    if before == 0:
                        text = "没有待上传的数据"
                    else:
                        up = Uploader(cfg, st, None)
                        n = up.push_once()
                        text = (f"成功推送 {n} 条" if n
                                else f"推送失败，{before} 条已留在本地（详见日志）")
                finally:
                    st.close()
            except Exception as e:
                text = f"出错：{type(e).__name__}: {e}"
            self.root.after(0, lambda: self.lbl_test.config(text=text))
            self.root.after(0, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def show(first_run: bool = False) -> int:
    return ConfigWindow(first_run=first_run).run()


if __name__ == "__main__":
    if sys.stdout:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(show())
