#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_upload_protocol.py —— 上报协议自测（不需要真 Supabase）

用法：
    # 终端 A：起假服务端
    py -3 -X utf8 dev/mock_server.py --postgrest 8766

    # 终端 B：
    py -3 -X utf8 dev/test_upload_protocol.py 8766

检查四件事：
    1. endpoint 的几种填写方式都能归一到 /rest/v1/rpc/push_sessions
    2. payload 形状是 {"rows": [...]}，字段类型对
    3. 第一次推送 → 服务端全写入
    4. 重复推送（故意把 uploaded 改回 0）→ 服务端返回 0，日志显示"重复已跳过"
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIN = HERE.parent / "win"
sys.path.insert(0, str(WIN))

PORT = sys.argv[1] if len(sys.argv) > 1 else "8766"
ROOT = f"http://127.0.0.1:{PORT}"

# 用临时目录当 %APPDATA%，绝不碰真实数据
TMP = Path(tempfile.mkdtemp(prefix="infocollect-test-"))
os.environ["INFOCOLLECT_HOME"] = str(TMP)

import config          # noqa: E402
from store import Store       # noqa: E402
from uploader import Uploader  # noqa: E402

FAILS: list[str] = []


class Log:
    """最小日志器：只把 uploader 想说的话打出来。"""
    def info(self, msg, *a):
        print("  [info] " + (msg % a if a else msg))

    def warning(self, msg, *a):
        print("  [warn] " + (msg % a if a else msg))

    def debug(self, msg, *a):
        pass


def check(name: str, ok: bool, extra: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + (f"　{extra}" if extra else ""))
    if not ok:
        FAILS.append(name)


def make_cfg(endpoint: str = ROOT, provider: str = "supabase") -> dict:
    cfg = config.DEFAULTS.copy()
    cfg["device_label"] = "测试机"
    cfg["upload"] = dict(config.DEFAULTS["upload"])
    cfg["upload"].update({
        "enabled": True, "provider": provider, "endpoint": endpoint,
        "token": "test-publishable-key", "include_title": True,
        "interval_hours": 4, "timeout_seconds": 5, "batch_size": 500,
    })
    return cfg


def main() -> int:
    print(f"临时数据目录：{TMP}\n")

    # ---------- 1. 地址归一化
    print("1) endpoint 归一化")
    store = Store(TMP / "infocollect.db")
    up = Uploader(make_cfg(), store, Log())
    expect = ROOT + "/rest/v1/rpc/push_sessions"
    for ep in (ROOT, ROOT + "/", ROOT + "/rest/v1", ROOT + "/rest/v1/",
               ROOT + "/rest/v1/sessions", expect):
        up.apply_config(make_cfg(ep))
        check(f"{ep.replace(ROOT, '<root>')} → 函数地址", up.url() == expect, up.url())
    up.apply_config(make_cfg(ROOT))
    check("generic 分支不改地址", Uploader(
        make_cfg(ROOT + "/api/sessions", "generic"), store, Log()).url() == ROOT + "/api/sessions")

    # ---------- 2. payload 形状
    print("\n2) payload 形状")
    now = int(time.time())
    for i in range(3):
        sid = store.open_session(now - 600 * (i + 1), "code.exe", f"文件{i}.py - PyCharm", "编码")
        store.close_session(sid, now - 600 * (i + 1) + 300)
    items = store.pending_sessions(500)
    payload = up.build_payload(items)
    check("是对象不是裸数组", isinstance(payload, dict))
    check("有 rows 键且是数组", isinstance(payload.get("rows"), list)
          and len(payload["rows"]) == 3)
    row = (payload.get("rows") or [{}])[0]
    check("必填字段齐全", all(k in row for k in (
        "device_id", "id", "hostname", "device_label", "start_ts", "end_ts",
        "app", "category", "title")))
    check("时间戳是整数", all(isinstance(row.get(k), int) for k in ("id", "start_ts", "end_ts")))
    print("  样例：" + json.dumps(row, ensure_ascii=False)[:160] + " …")

    # ---------- 3. 首推
    print("\n3) 第一次推送（应全新写入）")
    n = up.push_once()
    check("push_once 返回 3", n == 3, str(n))
    check("本地已标记 uploaded", store.pending_count() == 0, f"剩 {store.pending_count()} 条")

    # ---------- 4. 重推（幂等）
    print("\n4) 重复推送（模拟上次没来得及标记为已上传）")
    store.conn.execute("UPDATE sessions SET uploaded = 0")
    store.conn.commit()
    n2 = up.push_once()
    check("push_once 仍返回 3（成功，不算失败）", n2 == 3, str(n2))
    check("重复行被跳过而不是报错", store.pending_count() == 0)

    store.close()
    print("\n" + ("全部通过。" if not FAILS else f"失败 {len(FAILS)} 项：" + "；".join(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
