#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py —— 配置读写与路径管理

所有路径集中在这里，其它模块不许自己拼路径。
配置放 %APPDATA%\\InfoCollect\\，不放程序目录（将来打成 exe 可能装到只读位置）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "InfoCollect"

# 版本号唯一来源。改这里之后跑一次 build_exe.bat，exe 的文件属性会同步更新。
APP_VERSION = "0.3"

# 默认配置：新增字段一律加在这里，load() 会自动补齐，老配置文件不会因为缺字段崩掉
DEFAULTS: dict = {
    "sample_interval_seconds": 5,      # 采样间隔
    "idle_threshold_seconds": 300,     # 超过这么久没碰键鼠 = 离开
    "collect_window_title": True,      # 是否采集窗口标题
    "title_max_length": 120,           # 标题截断长度
    "title_blacklist": [],             # 进程名或 *关键词*，命中则不记标题（默认空 = 全采）
    "split_by_title": True,            # 会话是否按标题首段切分（False = 按程序切分）
    "work_unit_chars": 40,             # 标题首段保留多少字符用于判断"同一工作单位"
    "app_level_apps": [                # 这些程序不按标题切分，只按程序切分
        "chrome.exe", "msedge.exe", "firefox.exe", "iexplore.exe",
        "360se.exe", "qqbrowser.exe", "safari.exe",
    ],
    "switch_confirm_samples": 3,       # 切换程序要连续几次采样才确认（防止碎片）
    "category_map": {
        "pycharm64.exe": "编码",
        "code.exe": "编码",
        "devenv.exe": "编码",
        "idea64.exe": "编码",
        "goland64.exe": "编码",
        "sublime_text.exe": "编码",
        "notepad++.exe": "编码",
        "workbuddy.exe": "编码",
        "windowsterminal.exe": "编码",
        "cmd.exe": "编码",
        "powershell.exe": "编码",
        "chrome.exe": "浏览",
        "msedge.exe": "浏览",
        "firefox.exe": "浏览",
        "wechat.exe": "沟通",
        "weixin.exe": "沟通",
        "qq.exe": "沟通",
        "dingtalk.exe": "沟通",
        "feishu.exe": "沟通",
        "explorer.exe": "文件管理",
        "doubao.exe": "AI 助手",
    },
    "default_category": "其他",
    "autostart": False,
    "device_label": "",                # 这台机器的名字，如"台式机"/"笔记本"，多设备报表里用来区分
    "upload": {
        "enabled": False,          # 总开关，默认关；没有服务端时保持关闭
        "provider": "generic",     # generic = 自己写的服务端；supabase = PostgREST
        "endpoint": "",            # 如 https://example.com/api/sessions
        "token": "",               # generic 填设备 token；supabase 填 anon key
        "include_title": False,    # 是否把窗口标题也推上去（默认不传，见 README §8）
        "interval_hours": 4,       # 定时推送间隔（小时）
        "on_shutdown": True,       # 关机/注销时最后再推一次（尽力而为）
        "timeout_seconds": 10,     # 单次推送超时；跨境访问 3 秒太紧
        "batch_size": 500,         # 一次最多推多少条
    },
}


def app_dir() -> Path:
    """数据目录。可用 INFOCOLLECT_HOME 环境变量覆盖（测试用）。"""
    override = os.environ.get("INFOCOLLECT_HOME")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def config_path() -> Path:
    return app_dir() / "config.json"


def db_path() -> Path:
    return app_dir() / "infocollect.db"


def log_path() -> Path:
    return app_dir() / "infocollect.log"


def ensure_dir() -> Path:
    d = app_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _merge(defaults: dict, loaded: dict) -> dict:
    """把用户配置合并到默认值上：缺的补上，多的保留（便于将来加字段）。"""
    out = dict(defaults)
    for k, v in loaded.items():
        if isinstance(v, dict) and isinstance(defaults.get(k), dict):
            out[k] = _merge(defaults[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    """读配置。文件不存在、损坏、字段缺失，一律回退到默认值，绝不抛异常。"""
    path = config_path()
    if not path.exists():
        cfg = dict(DEFAULTS)
        save(cfg)                      # 第一次运行直接落一份，方便用户手改
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("配置文件根节点必须是对象")
        return _merge(DEFAULTS, raw)
    except Exception:
        return dict(DEFAULTS)


def save(cfg: dict) -> None:
    ensure_dir()
    path = config_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)                  # 原子替换，避免写一半断电导致配置损坏
