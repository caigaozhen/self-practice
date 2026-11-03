#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sampler.py —— 采样状态机（整个程序的心脏）

职责：每隔 N 秒看一眼"现在在用什么程序、人还在不在"，把这些片段
拼成一段段连续的会话，写进 SQLite。

状态只有两种：
    空闲态：没有正在进行的会话（sid == 0）
    会话态：有一段正在累加的会话

状态迁移：
    空闲 --(活跃且有前台窗口)--> 新建会话
    会话 --(程序/工作单位变了)--> 结算 + 新建
    会话 --(idle 超阈值 或 锁屏)--> 结算 --进入空闲态
    会话 --(检测到时间断档: 休眠/挂起)--> 结算到最后一次采样时刻，不补记
"""

from __future__ import annotations

import threading
import time
from collections import Counter

import classifier
import sanitize
import winapi
from store import Store


class Sampler:
    def __init__(self, cfg: dict, store: Store, log, uploader=None) -> None:
        self.cfg = cfg
        self.store = store
        self.log = log
        self.uploader = uploader          # 可为 None，表示不上报

        self.interval = max(1, int(cfg.get("sample_interval_seconds") or 5))
        self.idle_threshold = max(1, int(cfg.get("idle_threshold_seconds") or 300))
        self.collect_title = bool(cfg.get("collect_window_title", True))

        # 断档阈值：连续两个采样点的间隔超过这个值，就认为中间经历了休眠/挂起
        self.gap_threshold = max(self.interval * 3, 30)

        # 切换粘滞：新程序必须连续出现这么多次采样，才认定"真的切过去了"。
        # 否则在浏览器里点几下、Alt+Tab 瞄一眼微信，都会切出一条几秒的碎片。
        self.sticky = max(1, int(cfg.get("switch_confirm_samples") or 3))

        # ---- 会话态
        self.sid = 0
        self.start_ts = 0
        self.key: tuple[str, str] | None = None
        self.titles: Counter[str] = Counter()

        # ---- 待确认的切换
        self._pending: tuple[str, str] | None = None
        self._pending_n = 0
        self._pending_at = 0

        self.last_tick = 0
        self.last_hb = 0
        self._running = True
        self._paused = False              # 托盘"暂停采集"用，暂停时只写心跳不记账
        self._finalized = False
        self._slock = threading.RLock()   # 保护会话的开关，防止主线程与关机回调撞车

    # ------------------------------------------------------------ 会话操作

    def _open(self, now: int, app: str, title: str, category: str) -> None:
        unit = sanitize.work_unit(app, title, self.cfg)
        with self._slock:
            self.sid = self.store.open_session(now, app, title, category)
            self.start_ts = now
            self.key = (app, unit)
            self.titles = Counter()
            if title:
                self.titles[title] += 1
            self._pending, self._pending_n = None, 0

    def _close(self, end_ts: int) -> None:
        """结算当前会话。标题取出现次数最多的那个作为"代表标题"。"""
        with self._slock:
            if not self.sid:
                return
            sid, start_ts = self.sid, self.start_ts
            rep = self.titles.most_common(1)[0][0] if self.titles else ""
            try:
                self.store.close_session(sid, end_ts, rep or None)
            except Exception as e:
                self.log.warning("close_session 失败: %s", e)
            self.log.debug(
                "结算会话 id=%s app=%s 时长=%ss 代表标题=%r",
                sid,
                self.key[0] if self.key else "?",
                max(0, end_ts - start_ts),
                rep,
            )
            self.sid = 0
            self.start_ts = 0
            self.key = None
            self.titles = Counter()
            self._pending = None
            self._pending_n = 0

    # ------------------------------------------------------------ 运行时控制

    def apply_config(self, cfg: dict) -> None:
        """热更新配置。只更新采样相关的旋钮，不改会话状态。

        cfg 是就地改过的同一个 dict（托盘线程里 cfg.clear(); cfg.update(...)），
        所以这里必须重新读一遍派生值，否则 interval 之类还是旧值。
        """
        with self._slock:
            self.cfg = cfg
            self.interval = max(1, int(cfg.get("sample_interval_seconds") or 5))
            self.idle_threshold = max(1, int(cfg.get("idle_threshold_seconds") or 300))
            self.collect_title = bool(cfg.get("collect_window_title", True))
            self.gap_threshold = max(self.interval * 3, 30)
            self.sticky = max(1, int(cfg.get("switch_confirm_samples") or 3))
        self.log.info(
            "配置已热更新：间隔 %ss，闲置阈值 %ss，采集标题=%s",
            self.interval, self.idle_threshold, self.collect_title,
        )

    def pause(self) -> None:
        """暂停采集：结算当前会话，之后只写心跳。进程继续活着，托盘图标还在。"""
        with self._slock:
            if self._paused:
                return
            self._paused = True
        now = int(time.time())
        self._close(now)
        self._heartbeat(now, force=True)
        self.log.info("采集已暂停")

    def resume(self) -> None:
        with self._slock:
            if not self._paused:
                return
            self._paused = False
            self.last_tick = 0            # 清掉，否则恢复的那一刻会被当成"时间断档"
        self.log.info("采集已恢复")

    @property
    def paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------ 单次采样

    def tick(self, now: int | None = None) -> None:
        now = int(now if now is not None else time.time())

        # ⓪ 暂停态：什么都不记，只维持心跳（否则状态页会显示"未运行"）
        if self._paused:
            self.last_tick = now
            self._heartbeat(now)
            return

        # ① 断档检测：刚睡醒、或进程被挂起过
        if self.last_tick and (now - self.last_tick) > self.gap_threshold:
            self.log.info("检测到时间断档 %ss，按中断处理，不补记", now - self.last_tick)
            if self.sid:
                self._close(self.last_tick)      # 结束在"最后一次正常采样"时刻
            self.last_tick = now
            self._heartbeat(now, force=True)
            return

        # ② 人在不在
        idle = winapi.get_idle_seconds()
        locked = winapi.is_locked()
        if locked or idle >= self.idle_threshold:
            if self.sid:
                # 结束时刻取"最后一次键鼠动作"的时间，而不是现在——
                # 否则会把 threshold 那几分钟的闲置也算进工作时长
                self._close(now - int(min(idle, now)))
                self.log.debug("判定离开（locked=%s idle=%.0fs），已结算", locked, idle)
            self.last_tick = now
            self._heartbeat(now)
            return

        # ③ 采前台窗口
        fg = winapi.get_foreground()
        if not fg.ok:
            # 切换瞬间、锁屏过渡态拿不到窗口：跳过这一轮，不要误判为"换了程序"
            self.last_tick = now
            return

        title = ""
        if self.collect_title and not sanitize.is_blacklisted(fg.app, fg.title, self.cfg):
            title = sanitize.clean_title(fg.title, self.cfg)

        key = (fg.app, sanitize.work_unit(fg.app, title, self.cfg))

        # ④ 是否同一段工作（带粘滞确认，避免碎片会话）
        if not self.sid:
            self._open(now, fg.app, title, classifier.classify(fg.app, self.cfg))
        elif key == self.key:
            self._pending, self._pending_n = None, 0
            if title:
                self.titles[title] += 1
        else:
            if self._pending == key:
                self._pending_n += 1
            else:
                self._pending = key
                self._pending_n = 1
                self._pending_at = now

            if self._pending_n >= self.sticky:
                # 确认切换：把切换时刻回填到"第一次出现新程序"的那一刻，
                # 这样既不丢时间，也不会和上一段重叠
                at = max(self.start_ts + 1, self._pending_at)
                self._close(at)
                self._open(at, fg.app, title, classifier.classify(fg.app, self.cfg))

        self.last_tick = now
        self._heartbeat(now)
        # 定时推送（内部判断间隔，没到点就直接返回，开销只有一次比较）
        if self.uploader is not None:
            try:
                self.uploader.maybe_periodic(now)
            except Exception:
                self.log.exception("定时推送触发异常")

    def _heartbeat(self, now: int, force: bool = False) -> None:
        """每 30 秒写一次心跳，用于事后判断"程序是不是偷偷死了"。"""
        if force or (now - self.last_hb) >= 30:
            try:
                self.store.heartbeat(now)
            except Exception:
                pass
            self.last_hb = now

    # ------------------------------------------------------------ 主循环

    def _finalize(self) -> None:
        """收尾：结算当前会话 → 写心跳 → 最后一次推送。只会执行一次。"""
        with self._slock:
            if self._finalized:
                return
            self._finalized = True

        now = int(time.time())
        self._close(now)
        self._heartbeat(now, force=True)
        if self.uploader is not None:
            try:
                n = self.uploader.push_on_exit()
                if n:
                    self.log.info("退出前推送了 %d 条", n)
            except Exception:
                self.log.exception("退出前推送失败")
        self.log.info("采样已停止")

    def shutdown(self, reason: int | str = "") -> None:
        """外部要求退出（关机/注销/关闭窗口）。会尝试在系统杀掉我们之前收尾。"""
        self.log.info("收到退出请求(%s)，开始收尾", reason)
        self._running = False
        self._finalize()

    def run_forever(self) -> None:
        # 启动时先处理上次异常退出留下的"未结算会话"
        hb = self.store.last_heartbeat()
        if hb:
            n = self.store.close_dangling(hb)
            if n:
                self.log.info("补结算了 %d 条上次残留的会话（结束于 %s）", n, hb)

        self.log.info(
            "采样启动：间隔 %ss，闲置阈值 %ss，采集标题=%s",
            self.interval, self.idle_threshold, self.collect_title,
        )

        # 上次没推成功的数据，启动时补推一次（这就是"关机推送失败也不丢数据"的兜底）
        if self.uploader is not None and getattr(self.uploader, "ready", False):
            pending = self.store.pending_count()
            if pending:
                self.log.info("有 %d 条未上传，启动后补推", pending)
                threading.Thread(target=self.uploader.push_once, daemon=True).start()

        try:
            while self._running:
                try:
                    self.tick()
                except Exception:
                    self.log.exception("tick 异常，跳过本轮")
                # 用短睡眠切片，保证 Ctrl+C / 停止信号能及时响应
                slept = 0.0
                while self._running and slept < self.interval:
                    step = min(0.5, self.interval - slept)
                    time.sleep(step)
                    slept += step
        finally:
            self._finalize()

    def stop(self) -> None:
        self._running = False
