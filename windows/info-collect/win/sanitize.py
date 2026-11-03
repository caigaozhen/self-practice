#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sanitize.py —— 标题处理：截断、黑名单、工作单位归一化

这里只做字符串处理，不碰任何 Windows API，方便单测。
"""

from __future__ import annotations

# 标题里常见的分隔符：编辑器多为 "文件 - 项目 - IDE"，浏览器多为 "页面标题 - 站点"
_SEPARATORS = (" - ", " – ", " — ", " | ", " ｜ ", " · ")


def is_blacklisted(app: str, title: str, cfg: dict) -> bool:
    """命中黑名单返回 True。空列表 = 不过滤（当前默认）。"""
    patterns = cfg.get("title_blacklist") or []
    if not patterns:
        return False

    app_l = (app or "").lower()
    title_l = (title or "").lower()
    for pat in patterns:
        p = str(pat).lower().strip()
        if not p:
            continue
        if p.startswith("*") and p.endswith("*") and len(p) >= 3:
            if p[1:-1] in app_l or p[1:-1] in title_l:
                return True
        elif p.startswith("*"):
            if app_l.endswith(p[1:]) or title_l.endswith(p[1:]):
                return True
        elif p.endswith("*"):
            if app_l.startswith(p[:-1]) or title_l.startswith(p[:-1]):
                return True
        elif p == app_l:
            return True
    return False


def clean_title(title: str, cfg: dict) -> str:
    """规范化标题：去空白、按配置截断。"""
    if not title:
        return ""
    # 标题里的换行会污染日志和报表
    t = " ".join(str(title).split())
    limit = int(cfg.get("title_max_length") or 120)
    return t[:limit]


def work_unit(app: str, title: str, cfg: dict) -> str:
    """提取"工作单位"，用于判断两帧是否属于同一段工作。

    三种情况：
    1. 程序在 app_level_apps 里（浏览器等）：返回空串 → 该程序内不按标题切分。
       因为浏览器标题几乎每页都变，按标题切会产生大量几秒的碎片。
    2. split_by_title = False：返回空串，等价于"同一程序就是同一段"。
    3. 其余（编辑器、IDE）：取标题第一段，如 "bootstat.py - PyCharm" → "bootstat.py"，
       这样"在同一个项目里干活"算一段。
    """
    if not cfg.get("split_by_title", True):
        return ""
    if not title:
        return ""

    app_l = (app or "").lower()
    if app_l in {str(a).lower() for a in (cfg.get("app_level_apps") or [])}:
        return ""

    t = str(title)
    for sep in _SEPARATORS:
        if sep in t:
            t = t.split(sep, 1)[0]
            break
    t = " ".join(t.split()).lower()
    limit = int(cfg.get("work_unit_chars") or 40)
    return t[:limit]
