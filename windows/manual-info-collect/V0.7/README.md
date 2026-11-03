# V0.7 · 会话切分与 SQLite 落库

> **一句话目标**：把 V0.6 那种"每 5 秒一条日志"的原始记录，变成"一段一段的会话"存进 SQLite，并能按天汇总出「哪个程序用了多久」。

这是整个项目从"能看"到"能用"的分水岭。

---

## 前置条件

V0.6 完成：能稳定采到 `app / title / 空闲时长`。

---

## 一、先想清楚"会话"是什么

一条原始采样是"某一刻我在哪"。会话是"**连续处于同一目标**的一段时间"：

```
10:00:00 pycharm64.exe  main.py - PyCharm
10:00:05 pycharm64.exe  main.py - PyCharm
10:00:35 pycharm64.exe  utils.py - PyCharm     ← 换了文件，但还在同一程序
10:00:40 pycharm64.exe  main.py - PyCharm
```

切分规则（三个都要有）：

| 规则 | 取值 | 解决的问题 |
|---|---|---|
| 程序变了 | `app != current.app` | 切到别的程序 |
| 标题首段变了（可选） | `title[:40] != current.title[:40]` | 同一程序内换了文件 |
| **连续 N 次一致才切** | `switch_confirm_samples = 3` | 浏览器标题每敲一个字就变，否则 24 秒切出 6 段假会话 |

第三条是关键。没有它，数据会被撕成几千个碎片。对浏览器这类"标题高频变化"的程序，还应配置成**只按程序切分**（`app_level_apps`）。

另外：**空闲超过阈值（如 300 秒）要强制切断会话**，并把这段时间记为"离开"，不计入任何应用。

---

## 二、表结构

```sql
CREATE TABLE sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts   INTEGER NOT NULL,
    end_ts     INTEGER NOT NULL DEFAULT 0,   -- 0 = 还在进行中
    app        TEXT    NOT NULL,
    title      TEXT    NOT NULL DEFAULT '',
    category   TEXT    NOT NULL DEFAULT '其他',
    uploaded   INTEGER NOT NULL DEFAULT 0    -- 留给 V0.8
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

两个设计要点：

1. **`end_ts = 0` 表示"未结算"**。程序被强杀时一定会有这种残留行，所以启动时要先"补结算"（把 `end_ts` 设成最后一次心跳时间），否则它会永远挂着、时长虚增。
2. **`uploaded` 字段** 是给 V0.8 的上报用的，现在先建好，避免将来改表。

建议开启 WAL：`PRAGMA journal_mode=WAL`。采样线程写、报表读，WAL 下读写不互相阻塞。

---

## 三、状态机

```
        ┌──────────── 每次采样 ────────────┐
        ▼                                  │
  [当前会话存在?] ──否──► open_session() ───┤
        │是                                │
        ▼                                  │
  目标相同? ──是──► close 时不切，继续 ────┤
        │否                                │
        ▼                                  │
  连续 N 次不同? ──否──► 记待切换，先不动 ──┤
        │是                                │
        ▼                                  │
  close_session(now) + open_session() ─────┘
```

另外两个必须处理的场景：

- **空闲超阈值**：`close_session(last_active)`，然后置空当前会话；恢复时再新开
- **程序退出**：把当前会话结算掉（`end_ts = now`），不要留 `0`

---

## 四、并发

采样线程写库、报表/配置/上报可能同时读，SQLite 连接默认不能在多线程共用。

两种做法（选一种）：

| 做法 | 说明 |
|---|---|
| `check_same_thread=False` + `threading.RLock` | 简单直接，本项目采用 |
| 每线程一个连接 | 更彻底，但要处理 WAL 下的写冲突 |

锁要包住"取会话 + 判断 + 写"这一整段，而不只是单条 SQL——否则两次采样可能同时判定"需要切换"，开出两条会话。

---

## 五、实现步骤

1. 建 `store.py`：`SCHEMA` 常量、`Store` 类、`connect()` 里执行 `PRAGMA`
2. 实现 `open_session()` / `close_session()` / `session_between()` / `pending()`
3. `heartbeat(ts)`：每轮采样更新一次"最后活着的时间"到 `meta` 表
4. 启动时 `close_dangling(now)`：把所有 `end_ts = 0` 的行结算掉
5. `sampler.py` 里实现状态机（切分 + 粘滞 + 空闲）
6. `reporter.py`：按天查询 + 按 app / category 汇总 + 时长格式化（`1 小时 14 分`）
7. 托盘上加"查看今日报表"

---

## 坑

| 坑 | 表现 | 处理 |
|---|---|---|
| `end_ts = 0` 残留 | 今日时长虚增，出现 16 分钟的假会话 | 启动补结算 + 心跳夹取 |
| 没有粘滞确认 | 会话碎片化，几百段 | 连续 N 次一致才切 |
| 跨午夜 | 一段会话跨越 0 点，两天都算全段 | 报表按重叠时长切分 |
| 空闲没切断 | 离开 2 小时也算工作时间 | 超阈值强制 close |
| 忘开 WAL | 报表查询时采样写库报 `database is locked` | `PRAGMA journal_mode=WAL` |
| 锁粒度太细 | 并发开出两条会话 | 锁包住"判断+写入"整段 |

---

## 验收标准

- [ ] 连续写代码 10 分钟，库里出现 **1 段**会话（不是 120 段）
- [ ] 切到浏览器再切回来，出现 2 段以上，且时间不重叠
- [ ] 离开 6 分钟后回来，那 6 分钟不计入任何应用
- [ ] 任务管理器强杀进程后重启，没有 `end_ts = 0` 的行残留
- [ ] `report` 输出的"今日活跃"与手工累加库里的秒数一致
- [ ] 跨零点的会话在两天报表里各自只算自己那一半

---

## 完成后你应当能回答

- 为什么"连续 N 次才切换"是必需的？不做会怎样？
- `end_ts = 0` 这个约定解决了什么问题，又带来什么风险？
- 为什么锁要包住整段判断逻辑？
- 跨午夜的会话该怎么算才不重复？

---

## 参考文件

`windows/info-collect/win/store.py`（表结构、事务、锁）、`win/sampler.py`（状态机与粘滞切换）、`win/reporter.py`（汇总与格式化）。
