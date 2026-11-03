#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uploader.py —— 把本地会话推送到服务端

设计要点：
  1. **不丢数据优先**：推成功才把 uploaded 置 1，失败就留着下次再推
  2. **关机只是尽力而为**：Windows 关机只给几秒，超时就放弃；
     真正的保障是"下次启动补传"
  3. **短超时**：绝不拖住系统关机
  4. **幂等约定**：payload 里带 device_id + 每条的 id，服务端应按
     (device_id, id) 做 upsert，重复推送不会产生重复数据

支持两种 provider：

    generic     自己写的服务端，POST 一个带信封的 JSON 对象（见下）
    supabase    Supabase/PostgREST，POST 一个裸数组，靠 header 控制行为

generic 协议：

    POST <endpoint>
    Authorization: Bearer <token>
    Content-Type: application/json; charset=utf-8

    {
      "client": "InfoCollect/0.2",
      "device_id": "cc4844d4bba2",
      "sent_at": 1793322900,
      "sessions": [
        {"id": 12, "start_ts": ..., "end_ts": ..., "app": "pycharm64.exe",
         "title": "...", "category": "编码", "device_id": "...",
         "hostname": "DESKTOP-1", "device_label": "台式机"}
      ]
    }

supabase 协议（PostgREST RPC）：

    POST https://xxx.supabase.co/rest/v1/rpc/push_sessions
    apikey: <anon / publishable key>
    Authorization: Bearer <同一个 key>
    Content-Type: application/json

    {"rows": [ {"device_id": "...", "id": 12, "hostname": "...", ...}, ... ]}

  响应体是一个整数：实际写入的行数（重复的已跳过）。

为什么不再直接 POST /rest/v1/sessions：
  直接写表想表达"主键冲突就跳过"，只有一条路——Prefer: resolution=ignore-duplicates。
  但 PostgREST 实现这个语义靠的是 `ON CONFLICT DO NOTHING`，而它需要 SELECT 权限；
  anon 角色按设计只有 insert 没有 select，于是被 401 挡掉（这就是之前那个坑）。

  改走 security definer 函数后，ON CONFLICT 以函数属主身份执行，权限问题消失；
  anon 依旧读不到任何一行，权限模型一点没放松。
  函数还顺手返回写入行数，客户端因此能分辨"真新写入"和"重复跳过"。
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import config
from store import Store

CLIENT_TAG = f"InfoCollect/{config.APP_VERSION}"
TITLE_MAX = 500
RPC_PATH = "/rest/v1/rpc/push_sessions"


class Uploader:
    def __init__(self, cfg: dict, store: Store, log) -> None:
        self.cfg = cfg
        self.store = store
        self.log = log

        self.hostname = _hostname()
        self.apply_config(cfg)

        self._lock = threading.Lock()
        self.last_attempt = 0.0

    # ------------------------------------------------------------ 状态

    def apply_config(self, cfg: dict) -> None:
        """配置热更新。不改 last_attempt，避免改配置就把定时节奏打乱。"""
        self.cfg = cfg
        u = cfg.get("upload") or {}
        self.provider = str(u.get("provider") or "generic").strip().lower()
        self.enabled = bool(u.get("enabled"))
        self.endpoint = str(u.get("endpoint") or "").strip()
        self.token = str(u.get("token") or "").strip()
        self.include_title = bool(u.get("include_title", False))
        self.interval_seconds = max(60.0, float(u.get("interval_hours") or 4) * 3600)
        self.timeout = max(1.0, float(u.get("timeout_seconds") or 10))
        self.batch_size = max(1, int(u.get("batch_size") or 500))
        self.on_shutdown = bool(u.get("on_shutdown", True))
        self.device_label = str(cfg.get("device_label") or "").strip()[:40]

    @property
    def ready(self) -> bool:
        """配置齐全才推送。没填 endpoint 就静默跳过，不算错误。"""
        return self.enabled and self.endpoint.startswith(("http://", "https://"))

    def status_text(self) -> str:
        if not self.enabled:
            return "已关闭"
        if not self.ready:
            return "已启用但 endpoint 无效或为空"
        name = "Supabase" if self.provider == "supabase" else "自定义服务端"
        return (f"每 {self.interval_seconds / 3600:.1f} 小时 → {name} {self.url()}"
                f"（{'含' if self.include_title else '不含'}窗口标题）")

    def url(self) -> str:
        """实际 POST 的地址。

        Supabase 允许只填项目根地址，这里自动补成 /rest/v1/rpc/push_sessions——
        少一步手工拼接，也少一个填错的机会。

        兼容几种填法（都归一到同一个地址）：
            https://x.supabase.co
            https://x.supabase.co/
            https://x.supabase.co/rest/v1
            https://x.supabase.co/rest/v1/sessions     ← 旧版文档留下的写法
            https://x.supabase.co/rest/v1/rpc/push_sessions
        """
        ep = self.endpoint.rstrip("/")
        if self.provider != "supabase":
            return ep
        base = ep.split("/rest/v1")[0]      # 多余的后缀一律砍掉，以项目根为准
        return base + RPC_PATH

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json; charset=utf-8"}
        if self.provider == "supabase":
            # PostgREST 两个头都要：apikey 用来识别项目，Authorization 用来识别身份。
            # 走 RPC 就不需要 Prefer 了——幂等语义已经写在函数里。
            if self.token:
                h["apikey"] = self.token
                h["Authorization"] = f"Bearer {self.token}"
        elif self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    # ------------------------------------------------------------ 组包

    def _row(self, it: dict, device_id: str) -> dict:
        row = {
            "id": int(it["id"]),
            "start_ts": int(it["start_ts"]),
            "end_ts": int(it["end_ts"]),
            "app": it.get("app") or "",
            "category": it.get("category") or "",
            "device_id": it.get("device_id") or device_id,
            "hostname": self.hostname,
            "device_label": self.device_label,
            # 不传标题也要给个空串，不能省掉这个键：
            # jsonb_to_recordset 遇到缺键会给出 NULL，而 title 列是 not null，
            # 服务端就会 23502（真实踩过：400 null value in column "title"）。
            "title": ((it.get("title") or "")[:TITLE_MAX] if self.include_title else ""),
        }
        return row

    def build_payload(self, items: list[dict], now: float | None = None) -> dict | list:
        did = self.store.device_id()
        rows = [self._row(it, did) for it in items]
        if self.provider == "supabase":
            # RPC 的参数名必须和 SQL 里的 push_sessions(rows jsonb) 对上
            return {"rows": rows}
        return {
            "client": CLIENT_TAG,
            "device_id": did,
            "sent_at": int(now if now is not None else time.time()),
            "sessions": rows,
        }

    # ------------------------------------------------------------ 推送

    def push_once(self, timeout: float | None = None, dry_run: bool = False) -> int:
        """推一批。返回成功推送的条数，0 表示没推或失败。"""
        if not self.ready:
            return 0
        # 同一时刻只允许一个推送在跑（定时推送和关机推送可能撞车）
        if not self._lock.acquire(timeout=1.0):
            self.log.debug("已有推送在进行，跳过本次")
            return 0

        try:
            items = self.store.pending_sessions(self.batch_size)
            if not items:
                return 0

            payload = self.build_payload(items)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            if dry_run:
                self.log.info("[dry-run] 将推送 %d 条到 %s，payload 预览：%s",
                              len(items), self.url(),
                              json.dumps(payload, ensure_ascii=False)[:300])
                return 0

            req = urllib.request.Request(
                self.url(), data=body, headers=self._headers(), method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                code = getattr(resp, "status", 200)
                body = ""
                if self.provider == "supabase":
                    try:
                        body = resp.read(4096).decode("utf-8", "replace")
                    except Exception:
                        body = ""
                if 200 <= code < 300:
                    self.store.mark_uploaded([it["id"] for it in items])
                    self.last_attempt = time.time()
                    written = self._written_count(body, len(items))
                    # 记一笔，配置界面要显示"上次推送 xx 前"，否则用户没处确认同步状态
                    try:
                        self.store.set_meta("last_upload_at", int(self.last_attempt))
                        self.store.set_meta("last_upload_count", len(items))
                    except Exception:
                        pass
                    if written is None or written >= len(items):
                        self.log.info("已推送 %d 条到 %s", len(items), self.url())
                    else:
                        self.log.info("已推送 %d 条，服务端新写入 %d 条（%d 条重复，已跳过）",
                                      len(items), written, len(items) - written)
                    return len(items)
                self.log.warning("推送失败：HTTP %s", code)
                return 0

        except urllib.error.HTTPError as e:
            # 把服务端的错误信息也捞出来，否则 401/404 只能靠猜
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            self.log.warning("推送失败：HTTP %s %s %s（数据保留，稍后重试）",
                             e.code, e.reason, detail)
        except Exception as e:
            # 网络不通、超时、DNS 失败都在这里——绝不向上抛，不能影响采集
            self.log.warning("推送失败：%s（数据保留，稍后重试）", e)
        finally:
            self._lock.release()
        return 0

    @staticmethod
    def _written_count(body: str, sent: int) -> int | None:
        """从 RPC 响应里取"实际写入行数"，取不到就返回 None（按全成功处理）。

        为什么要区分：重复推送时函数返回 0，但这是**正确结果**，不能算失败——
        否则本地那些行永远标记不上 uploaded，会无限重推同一批。
        """
        try:
            v = json.loads(body)
        except Exception:
            return None
        if isinstance(v, bool):          # bool 是 int 的子类，先排除
            return None
        if isinstance(v, int):
            return max(0, min(v, sent))
        if isinstance(v, str) and v.strip().isdigit():
            return max(0, min(int(v), sent))
        return None

    def maybe_periodic(self, now: float) -> None:
        """由采样循环每轮调用。到点了就丢到后台线程去推，不阻塞采集。"""
        if not self.ready:
            return
        if now - self.last_attempt < self.interval_seconds:
            return
        self.last_attempt = now          # 先占位，避免每轮都触发
        threading.Thread(target=self.push_once, daemon=True).start()

    def push_on_exit(self) -> int:
        """关机/注销时的最后一次推送。短超时，失败就算了。"""
        if not self.ready or not self.on_shutdown:
            return 0
        self.log.info("退出前推送最后一次（超时 %.1fs）", min(self.timeout, 2.0))
        return self.push_once(timeout=min(self.timeout, 2.0))


def _hostname() -> str:
    """机器名。多设备时比一串随机 hex 好认得多。"""
    try:
        return socket.gethostname()[:64]
    except Exception:
        return ""
