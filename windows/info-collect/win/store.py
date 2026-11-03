#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store.py —— SQLite 存储层

只有这一层碰 SQL，其它模块一律通过方法调用。表结构见 README §4。

约定：
  end_ts = 0 表示"会话还在进行中"（程序被强杀时会残留这种行，
  启动时用 close_dangling() 补结算）。
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts    INTEGER NOT NULL,
    end_ts      INTEGER NOT NULL DEFAULT 0,
    app         TEXT    NOT NULL,
    title       TEXT    NOT NULL DEFAULT '',
    category    TEXT    NOT NULL DEFAULT '其他',
    device_id   TEXT    NOT NULL DEFAULT '',
    uploaded    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_ts);
CREATE INDEX IF NOT EXISTS idx_sessions_app   ON sessions(app);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：允许将来把写库放到别的线程，现在单线程也兼容
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # WAL：读写不互相阻塞，长时间运行更稳
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        # 采样线程、上传线程、关机回调可能同时访问，用可重入锁串行化
        self._lock = threading.RLock()

    # ------------------------------------------------------------ meta

    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
            self.conn.commit()

    def device_id(self) -> str:
        """本机标识。第一次运行时生成，之后固定不变（为将来多设备合并预留）。"""
        did = self.get_meta("device_id")
        if not did:
            did = uuid.uuid4().hex[:12]
            self.set_meta("device_id", did)
        return did

    def device_label(self) -> str:
        """这台机器的显示名。空表示还没起名，报表里退回用 hostname。"""
        return self.get_meta("device_label")

    def set_device_label(self, label: str) -> None:
        self.set_meta("device_label", str(label)[:40])

    # ------------------------------------------------------------ 会话读写

    def open_session(self, start_ts: int, app: str, title: str, category: str) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO sessions(start_ts, end_ts, app, title, category, device_id) "
                "VALUES(?, 0, ?, ?, ?, ?)",
                (int(start_ts), app, title, category, self.device_id()),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def close_session(self, session_id: int, end_ts: int, title: str | None = None) -> None:
        """结算会话。end_ts 若小于 start_ts，会被夹到 start_ts + 1，避免出现零长度。"""
        with self._lock:
            if title is None:
                self.conn.execute(
                    "UPDATE sessions SET end_ts = MAX(?, start_ts + 1) WHERE id = ?",
                    (int(end_ts), int(session_id)),
                )
            else:
                self.conn.execute(
                    "UPDATE sessions SET end_ts = MAX(?, start_ts + 1), title = ? WHERE id = ?",
                    (int(end_ts), title, int(session_id)),
                )
            self.conn.commit()

    def heartbeat(self, ts: int) -> None:
        self.set_meta("last_heartbeat", int(ts))

    def last_heartbeat(self) -> int:
        try:
            return int(self.get_meta("last_heartbeat", "0") or 0)
        except ValueError:
            return 0

    def close_dangling(self, end_ts: int) -> int:
        """把上次异常退出遗留的未结算会话补上 end_ts。返回处理条数。"""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE sessions SET end_ts = MAX(?, start_ts + 1) WHERE end_ts = 0",
                (int(end_ts),),
            )
            self.conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------ 上传队列

    def pending_sessions(self, limit: int = 500) -> list[dict]:
        """取出还没上传的已结算会话（end_ts > 0）。正在进行的会话不推。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, start_ts, end_ts, app, title, category, device_id "
                "FROM sessions WHERE uploaded = 0 AND end_ts > 0 "
                "ORDER BY id LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def pending_count(self) -> int:
        with self._lock:
            return int(self.conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE uploaded = 0 AND end_ts > 0"
            ).fetchone()[0])

    def mark_uploaded(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self.conn.executemany(
                "UPDATE sessions SET uploaded = 1 WHERE id = ?", [(int(i),) for i in ids]
            )
            self.conn.commit()

    # ------------------------------------------------------------ 查询

    def sessions_between(self, t0: int, t1: int, now_ts: int | None = None) -> list[sqlite3.Row]:
        """取与 [t0, t1) 有重叠的会话。end_ts=0 的当作"到 now"。
        now_ts 不传就按 Python 的当前时间算。
        """
        import time

        now = int(now_ts if now_ts is not None else time.time())
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, start_ts, end_ts, app, title, category "
                "FROM sessions WHERE start_ts < ? AND (end_ts = 0 OR end_ts > ?) "
                "ORDER BY start_ts",
                (int(t1), int(t0)),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d["end_ts"] == 0:
                d["end_ts"] = max(now, d["start_ts"] + 1)
            out.append(d)
        return out

    def total_sessions(self) -> int:
        with self._lock:
            return int(self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])

    def wipe(self) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM sessions")
            self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass
