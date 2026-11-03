#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reporter.py —— 文本报表

把数据库里的会话按"天"聚合，输出分类占比、程序排行、以及明细。
会话可能跨天，这里按"与当天的重叠时长"计算，不会多算。

用法（由 app.py 调用）：
    report(store, day)      # day 为 datetime.date，None 表示今天
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from store import Store

WEEKDAYS = "一二三四五六日"
BAR_WIDTH = 16


def day_bounds(day: date) -> tuple[int, int]:
    """本地时间当天 00:00 到次日 00:00 的 Unix 时间戳。"""
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def fmt_duration(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{s} 秒"
    if s < 3600:
        return f"{s // 60} 分"
    return f"{s // 3600} 小时 {(s % 3600) // 60} 分"


def _bar(ratio: float) -> str:
    n = max(0, min(BAR_WIDTH, int(round(ratio * BAR_WIDTH))))
    return "█" * n


def collect(store: Store, day: date) -> dict:
    """返回 {'total': 秒, 'by_category': {}, 'by_app': {}, 'rows': [...]}"""
    t0, t1 = day_bounds(day)

    # end_ts=0 的会话表示"还在进行中"，默认算到此刻。
    # 但如果程序其实早就没在跑了（心跳停在很久以前），按"此刻"算会让这段
    # 时长无限虚增——你昨晚被强杀，今天看报表就是"活跃 18 小时"。
    # 所以心跳很旧时，把正在进行的会话夹到心跳时刻。
    now = int(time.time())
    hb = store.last_heartbeat()
    ref = hb if (hb and now - hb > 120) else now

    rows = store.sessions_between(t0, t1, now_ts=ref)

    by_cat: dict[str, int] = defaultdict(int)
    by_app: dict[str, int] = defaultdict(int)
    total = 0
    detail = []

    for r in rows:
        s = max(int(r["start_ts"]), t0)
        e = min(int(r["end_ts"]), t1)
        sec = max(0, e - s)
        if sec <= 0:
            continue
        total += sec
        by_cat[r["category"] or "其他"] += sec
        by_app[r["app"] or "unknown.exe"] += sec
        detail.append(
            {
                "start": s,
                "end": e,
                "seconds": sec,
                "app": r["app"],
                "category": r["category"],
                "title": r["title"] or "",
            }
        )

    return {
        "total": total,
        "by_category": dict(by_cat),
        "by_app": dict(by_app),
        "rows": detail,
    }


def render(store: Store, day: date | None = None, top_apps: int = 10, tail: int = 10) -> str:
    day = day or date.today()
    data = collect(store, day)
    total = data["total"]

    lines: list[str] = []
    lines.append("=" * 62)
    lines.append(f" {day.strftime('%Y-%m-%d')}（周{WEEKDAYS[day.weekday()]}） 时间去向")
    lines.append("=" * 62)

    if total == 0:
        lines.append("")
        lines.append(" 这一天没有记录。")
        lines.append(" 可能是程序没在运行，或者数据文件被清空了。")
        lines.append("")
        lines.append(f" 数据文件：{store.path}")
        return "\n".join(lines)

    lines.append(f" 活跃总时长：{fmt_duration(total)}")
    lines.append(f" 会话段数：{len(data['rows'])}")
    lines.append("")

    # ---- 分类
    lines.append("── 分类 ──")
    for cat, sec in sorted(data["by_category"].items(), key=lambda x: -x[1]):
        ratio = sec / total
        lines.append(
            f"  {cat:<8} {fmt_duration(sec):>12}  {ratio * 100:5.1f}%  {_bar(ratio)}"
        )
    lines.append("")

    # ---- 程序排行
    lines.append(f"── 程序 Top {top_apps} ──")
    apps = sorted(data["by_app"].items(), key=lambda x: -x[1])[:top_apps]
    for app, sec in apps:
        ratio = sec / total
        lines.append(f"  {app:<26} {fmt_duration(sec):>12}  {ratio * 100:5.1f}%")
    lines.append("")

    # ---- 明细
    if tail > 0:
        lines.append(f"── 最近 {tail} 段 ──")
        for d in data["rows"][-tail:]:
            t_start = datetime.fromtimestamp(d["start"]).strftime("%H:%M:%S")
            t_end = datetime.fromtimestamp(d["end"]).strftime("%H:%M:%S")
            title = d["title"][:34]
            lines.append(
                f"  {t_start}-{t_end} {fmt_duration(d['seconds']):>10}  "
                f"{d['app']:<20} {d['category']:<6} {title}"
            )

    lines.append("")
    lines.append(f" 数据文件：{store.path}")
    return "\n".join(lines)
