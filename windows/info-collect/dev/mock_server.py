#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mock_server.py —— 本地假服务端，用来测试上报链路和手机端界面

两种模式：

  ① generic（默认）—— 什么都不实现，只把收到的 JSON 打印出来
        py -3 -X utf8 mock_server.py
        配置："upload": {"endpoint": "http://127.0.0.1:8765/api/sessions"}

  ② postgrest —— 模拟 Supabase 的协议，连手机端的登录和查询都能跑
        py -3 -X utf8 mock_server.py --postgrest
        配置："upload": {"provider": "supabase", "endpoint": "http://127.0.0.1:8765"}

     它会做真正的协议校验，所以也是一个"合规性检查器"：
       - 地址必须是 /rest/v1/rpc/push_sessions
       - body 必须是 {"rows": [...]}（参数名要和 SQL 里的 push_sessions(rows jsonb) 一致）
       - 必须有 apikey 头
       - 每行必须有 device_id + id，时间戳必须是整数
     不合格会返回 400 并在控制台说明原因。返回值是"实际写入行数"，
     重复推送同一批会返回 0——和真实数据库函数的行为一致。

postgrest 模式下还实现了三个给手机端用的端点：
    POST /auth/v1/token?grant_type=password      任意邮箱密码都通过（本地模拟）
    GET  /rest/v1/v_daily?day=eq.YYYY-MM-DD      返回构造的当日汇总
    GET  /rest/v1/v_devices                      返回构造的设备列表

所以手机页面在真项目建好之前，可以先指着这个假服务端看效果。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

POSTGREST = "--postgrest" in sys.argv

# 记录"已经写进库里"的 (device_id, id)，用来模拟 on conflict do nothing。
# 放在进程内存里，重启就清空——正好对应"重跑一次又都是新的"。
SEEN: set[tuple[str, int]] = set()


# ---------------------------------------------------------------- 假数据

DEVICES = [
    ("dev-desk01", "台式机"),
    ("dev-lap02", "笔记本"),
]
CATEGORY_APPS = [
    ("编码", ["pycharm64.exe", "code.exe", "windowsterminal.exe"], 3.6),
    ("浏览", ["msedge.exe", "chrome.exe"], 1.5),
    ("沟通", ["weixin.exe", "dingtalk.exe"], 0.7),
    ("AI 助手", ["doubao.exe"], 0.9),
    ("其他", ["explorer.exe", "notepad.exe"], 0.5),
]


def fake_daily(day: str) -> list[dict]:
    """按日期生成稳定的假数据：同一天永远返回同一份，方便对比。"""
    seed = int(hashlib.md5(day.encode()).hexdigest()[:8], 16)
    rows = []
    for di, (dev_id, dev_name) in enumerate(DEVICES):
        factor = 1.0 if di == 0 else 0.55          # 笔记本时间少一些
        for ci, (cat, apps, weight) in enumerate(CATEGORY_APPS):
            for ai, app in enumerate(apps):
                rnd = ((seed >> ((di * 7 + ci * 3 + ai) % 24)) & 0xFF) / 255.0
                secs = int(weight * factor * (900 + rnd * 2700))
                if secs < 60:
                    continue
                rows.append({
                    "day": day,
                    "device_id": dev_id,
                    "device_name": dev_name,
                    "app": app,
                    "category": cat,
                    "seconds": secs,
                    "segments": 1 + (seed + ci + ai) % 6,
                })
    rows.sort(key=lambda r: -r["seconds"])
    return rows


def fake_devices(day: str) -> list[dict]:
    rows = fake_daily(day)
    out = {}
    for r in rows:
        d = out.setdefault(r["device_id"], {
            "device_id": r["device_id"], "device_name": r["device_name"],
            "first_seen": 0, "last_seen": 0, "sessions": 0,
        })
        d["sessions"] += r["segments"]
    return list(out.values())


# ---------------------------------------------------------------- 服务

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # 支持 keep-alive，浏览器端更顺

    # ---- 通用响应

    def _send(self, code: int, payload=None, raw: bytes | None = None) -> None:
        if raw is None:
            raw = b"" if payload is None else json.dumps(
                payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        # 手机端是从浏览器发的，必须给 CORS 头，否则一律被拦
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers",
                         "apikey, authorization, content-type, prefer, accept-profile")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "content-range")
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def log_message(self, *args) -> None:
        pass

    def _now(self) -> str:
        return datetime.datetime.now().strftime("%H:%M:%S")

    # ---- 预检

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204)

    # ---- GET

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)

        if path.startswith("/rest/v1"):
            if not self.headers.get("apikey") and not self.headers.get("Authorization"):
                self._send(401, {"message": "缺少 apikey"})
                return

        if path in ("/rest/v1/", "/rest/v1"):
            self._send(200, {"openapi": "3.0.0", "info": {"title": "mock"}})
            return

        if path == "/rest/v1/v_daily":
            day = (qs.get("day") or ["eq." + datetime.date.today().isoformat()])[0]
            day = day[3:] if day.startswith("eq.") else day
            rows = fake_daily(day)
            print(f"[{self._now()}] GET v_daily day={day} → {len(rows)} 行", flush=True)
            self._send(200, rows)
            return

        if path == "/rest/v1/v_devices":
            rows = fake_devices(datetime.date.today().isoformat())
            self._send(200, rows)
            return

        if path == "/rest/v1/sessions":
            self._send(200, [])
            return

        self._send(404, {"message": "not found: " + path})

    # ---- POST

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        now = self._now()

        if path.startswith("/auth/v1/token"):
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                body = {}
            mode = (qs.get("grant_type") or ["password"])[0]
            print(f"[{now}] POST /auth/v1/token ({mode}) email={body.get('email')}", flush=True)
            if mode == "password" and (not body.get("email") or not body.get("password")):
                self._send(400, {"error": "invalid_grant",
                                 "error_description": "email 和 password 都要有"})
                return
            self._send(200, {
                "access_token": "mock-access-token",
                "refresh_token": "mock-refresh-token",
                "expires_in": 3600,
                "token_type": "bearer",
                "user": {"email": body.get("email") or "mock@local"},
            })
            return

        if path == "/rest/v1/rpc/push_sessions":
            print(f"[{now}] POST /rest/v1/rpc/push_sessions  {length} 字节", flush=True)
            self._check_rpc(raw)
            return

        if path == "/rest/v1/sessions":
            # 旧协议（直接写表）。留着是为了能验证"升级前的客户端"还能不能用。
            print(f"[{now}] POST /rest/v1/sessions  {length} 字节（旧协议）", flush=True)
            self._check_postgrest(raw)
            return

        # 非 Supabase 协议的老接口
        print(f"[{now}] POST {path}  {length} 字节  "
              f"auth={self.headers.get('Authorization') or '-'}", flush=True)
        self._handle_generic(raw)
        return

    # ---- 两种协议的校验与打印

    def _check_rpc(self, raw: bytes) -> bool:
        """校验新协议：POST /rest/v1/rpc/push_sessions，body 形如 {"rows": [...]}。

        返回值和真函数一样是整数：实际写入行数（这里用内存 set 模拟主键去重）。
        """
        problems = []
        if not self.headers.get("apikey"):
            problems.append("缺少 apikey 头")

        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            problems.append(f"body 不是合法 JSON：{e}")
            data = None

        rows = None
        if isinstance(data, dict):
            rows = data.get("rows")
            if not isinstance(rows, list):
                problems.append('body 必须是 {"rows": [...]}，参数名要和 push_sessions(rows jsonb) 一致')
        elif data is not None:
            problems.append('body 必须是 {"rows": [...]} 对象；裸数组是旧的直接写表协议')

        if isinstance(rows, list):
            for i, r in enumerate(rows[:20]):
                if not isinstance(r, dict):
                    problems.append(f"第 {i+1} 行不是对象")
                    continue
                if not r.get("device_id") or r.get("id") is None:
                    problems.append(f"第 {i+1} 行缺 device_id 或 id（这俩是主键）")
                for k in ("start_ts", "end_ts", "id"):
                    if not isinstance(r.get(k), int) or isinstance(r.get(k), bool):
                        problems.append(f"第 {i+1} 行 {k} 必须是整数")

        if problems:
            for p in problems:
                print(f"  ✗ {p}", flush=True)
            print(flush=True)
            self._send(400, {"code": "PGRST102", "message": "; ".join(problems)})
            return False

        # 模拟 on conflict (device_id, id) do nothing
        new = 0
        for r in rows:
            key = (r["device_id"], int(r["id"]))
            if key not in SEEN:
                SEEN.add(key)
                new += 1

        print(f"  ✓ 协议正确：apikey ✓  rows 数组 ✓  {len(rows)} 行，新写入 {new} 行、"
              f"重复跳过 {len(rows) - new} 行", flush=True)
        for r in rows[:5]:
            dur = int(r.get("end_ts", 0)) - int(r.get("start_ts", 0))
            print(f"    - {r.get('device_label') or r.get('hostname') or r.get('device_id')}"
                  f"  id={r.get('id')}  {r.get('app')}  {dur}s  [{r.get('category')}]"
                  f"  {(r.get('title') or '(未传标题)')[:24]}", flush=True)
        if len(rows) > 5:
            print(f"    … 另外 {len(rows) - 5} 行", flush=True)
        print(flush=True)
        self._send(200, new)          # 真函数也返回一个整数
        return True

    def _check_postgrest(self, raw: bytes) -> bool:
        """严格按 PostgREST 的约定校验，不合格就报错——这正是它的价值。"""
        problems = []
        if not self.headers.get("apikey"):
            problems.append("缺少 apikey 头")
        prefer = (self.headers.get("Prefer") or "")
        if "resolution=ignore-duplicates" not in prefer:
            problems.append("Prefer 头缺少 resolution=ignore-duplicates（会导致重复推送报错）")

        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            problems.append(f"body 不是合法 JSON：{e}")
            data = None

        if data is not None and not isinstance(data, list):
            problems.append("body 必须是裸数组 []，不能是带信封的对象")

        if problems:
            for p in problems:
                print(f"  ✗ {p}", flush=True)
            print(flush=True)
            self._send(400, {"code": "PGRST102", "message": "; ".join(problems)})
            return False

        print(f"  ✓ 协议正确：apikey ✓  Prefer ✓  数组 ✓", flush=True)
        print(f"  Prefer: {prefer}", flush=True)
        if data:
            print(f"  收到 {len(data)} 行：", flush=True)
            for r in data[:5]:
                dur = int(r.get("end_ts", 0)) - int(r.get("start_ts", 0))
                print(f"    - {r.get('device_label') or r.get('hostname') or r.get('device_id')}"
                      f"  id={r.get('id')}  {r.get('app')}  {dur}s  [{r.get('category')}]"
                      f"  {(r.get('title') or '(未传标题)')[:24]}", flush=True)
            if len(data) > 5:
                print(f"    … 另外 {len(data) - 5} 行", flush=True)
        print(flush=True)
        self._send(201)
        return True

    def _handle_generic(self, raw: bytes) -> None:
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            print(f"  ✗ 不是合法 JSON：{e}", flush=True)
            data = None

        if isinstance(data, dict):
            sessions = data.get("sessions") or []
            print(f"  client={data.get('client')}  device={data.get('device_id')}  "
                  f"条数={len(sessions)}", flush=True)
            for s in sessions[:5]:
                dur = int(s.get("end_ts", 0)) - int(s.get("start_ts", 0))
                print(f"    - id={s.get('id')}  {s.get('app')}  {dur}s  "
                      f"[{s.get('category')}]  {(s.get('title') or '')[:30]}", flush=True)
            if len(sessions) > 5:
                print(f"    … 另外 {len(sessions) - 5} 条", flush=True)
        print(flush=True)
        self._send(200, {"ok": True})


def main() -> None:
    port = 8765
    for a in sys.argv[1:]:
        if a.isdigit():
            port = int(a)
    mode = "postgrest（模拟 Supabase）" if POSTGREST else "generic"
    print(f"mock server 已启动 [模式 {mode}]：http://127.0.0.1:{port}")
    if POSTGREST:
        print(f"  上报地址：http://127.0.0.1:{port}（provider 填 supabase，会自动补 /rest/v1/rpc/push_sessions）")
        print(f"  手机页面：把「项目地址」填 http://127.0.0.1:{port}，邮箱密码随便填")
    else:
        print(f"  上报地址：http://127.0.0.1:{port}/api/sessions")
    print("Ctrl+C 停止\n")
    try:
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
