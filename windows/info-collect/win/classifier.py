#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classifier.py —— 进程名 → 分类

规则：先查配置里的 category_map（精确匹配，大小写不敏感），查不到归到 default_category。
将来要支持通配符的话，在这里加，不要散到别处。
"""

from __future__ import annotations


def classify(app: str, cfg: dict) -> str:
    """给进程名归类。app 传小写进程名，如 "pycharm64.exe"。"""
    app_l = (app or "").lower()
    mapping = cfg.get("category_map") or {}

    # 精确匹配（配置里的 key 也做小写处理，允许用户随手写大小写）
    for key, value in mapping.items():
        if str(key).lower() == app_l:
            return str(value) or "其他"

    return str(cfg.get("default_category") or "其他")
