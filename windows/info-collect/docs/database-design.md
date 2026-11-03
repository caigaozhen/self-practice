# InfoCollect 数据库设计

> 文档定位：描述「数据长什么样、放在哪、怎么保证不重不漏」。
> 需求见 [requirements.md](requirements.md)，流程与模块见 [detailed-design.md](detailed-design.md)，
> 历史决策见 [design.md](design.md) §4 / §12。
>
> 版本：v0.3（2026-11-02）

---

## 1. 设计目标与原则

| 原则 | 落地方式 |
|---|---|
| 本地优先 | 本地 SQLite 是唯一事实来源；云端只是可选副本，断网/未配置时功能完整 |
| 会话粒度 | 不按固定采样行存，按「一段连续活跃」存一条，查询天然是区间求和 |
| 幂等同步 | 客户端可能重发；云端按 `(device_id, id)` 唯一，重复批次不产生重复行 |
| 最小权限 | 桌面端只写、手机端登录后只读；anon key 泄露也读不到数据 |
| 可诊断 | 心跳、上传时间、上传条数写入 `meta`，用于判断「程序是否还在跑 / 是否同步」 |
| 可清空 | 一条 `wipe` 删除全部会话，不影响配置与本机标识 |

---

## 2. 数据流与边界

```
┌────────────────────── Windows 采集端 ──────────────────────┐
│  winapi 采样 → sampler 会话状态机 → store.py（唯一 SQL 层） │
│                                      │                     │
│                          ┌───────────┴────────────┐        │
│                          ▼                        ▼        │
│              %APPDATA%\InfoCollect\        上传队列查询      │
│              infocollect.db (SQLite)       (uploaded=0)     │
└──────────────────────────┬─────────────────────────────────┘
                           │ 可选：HTTP POST（每 4 小时 / 关机 / 启动 / 手动）
                           ▼
┌────────────────────── Supabase（PostgreSQL）────────────────┐
│  public.sessions（事实表，RLS：anon 只 insert）              │
│  public.v_daily / v_devices（security_invoker 视图）        │
│  public.push_sessions(rows jsonb)（security definer 函数）   │
└──────────────────────────┬─────────────────────────────────┘
                           │ 登录后 SELECT
                           ▼
                    mobile（uni-app 查看端）
```

边界约定：

- 只有 `win/store.py` 直接执行 SQL；其它模块通过方法访问。
- 只有 `win/uploader.py` 发起网络请求；采集线程不直接联网。
- 云端不保存 `uploaded` 字段；「本地标记上传成功」由客户端负责。

---

## 3. 本地 SQLite

### 3.1 位置与连接参数

| 项 | 值 | 说明 |
|---|---|---|
| 文件 | `%APPDATA%\InfoCollect\infocollect.db` | 可用 `INFOCOLLECT_HOME` 覆盖（测试用） |
| 日志模式 | `PRAGMA journal_mode=WAL` | 采集写入时仍可用 DB Browser 读取 |
| 同步级别 | `PRAGMA synchronous=NORMAL` | 常驻写入场景下兼顾性能与安全 |
| 线程 | `check_same_thread=False` + `threading.RLock` | 采样线程、上传线程、关机回调可能并发 |
| 建表 | 启动时 `executescript`，全部 `IF NOT EXISTS` | 幂等，不需要迁移脚本 |

### 3.2 表结构：`sessions`

```sql
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
```

数据字典：

| 字段 | 类型 | 约束 / 默认 | 语义 |
|---|---|---|---|
| `id` | INTEGER | PK，自增 | 本机局部主键；云端需与 `device_id` 组合才有全局唯一性 |
| `start_ts` | INTEGER | NOT NULL | 会话开始，Unix 秒（UTC 绝对值，展示时转本地时区） |
| `end_ts` | INTEGER | NOT NULL，默认 0 | 会话结束；**0 表示仍在进行中** |
| `app` | TEXT | NOT NULL | 小写进程名，如 `pycharm64.exe`；取不到时为 `unknown.exe` |
| `title` | TEXT | NOT NULL，默认 `''` | 会话代表标题（出现次数最多者），已按配置截断 |
| `category` | TEXT | NOT NULL，默认 `其他` | 分类映射结果 |
| `device_id` | TEXT | NOT NULL，默认 `''` | 12 位十六进制本机标识，首次运行生成 |
| `uploaded` | INTEGER | NOT NULL，默认 0 | 0 = 待上传 / 1 = 已成功上传 |

索引用途：

| 索引 | 服务的查询 |
|---|---|
| `idx_sessions_start(start_ts)` | 报表按日期区间取会话（`sessions_between`） |
| `idx_sessions_app(app)` | 程序维度统计 / 人工排查 |

### 3.3 表结构：`meta`

```sql
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

当前代码实际写入的键：

| key | 写入方 | 语义 |
|---|---|---|
| `device_id` | `Store.device_id()` | 首次生成的 12 位机器标识，之后固定不变 |
| `device_label` | `cmd_device` / 配置界面 | 显示名（≤ 40 字符），空则报表退回 hostname |
| `last_heartbeat` | `Store.heartbeat()`（每 30 秒或强制） | 最后一次成功采样的 Unix 秒；用于判断是否在跑、补结算残留会话 |
| `last_upload_at` | `Uploader.push_once()` 成功后 | 上次推送成功的 Unix 秒；配置界面显示「上次推送 x 前」 |
| `last_upload_count` | `Uploader.push_once()` 成功后 | 上次推送条数 |

> `design.md` §4.2 提到的 `schema_version` 目前是**预留键**，代码没有写入。
> 现有建表策略是 `CREATE TABLE IF NOT EXISTS`，字段变更需要手写 `ALTER TABLE`。

### 3.4 状态与不变量

| 不变量 | 保证方式 |
|---|---|
| 同一时刻最多一个未结算会话 | `Sampler` 单线程状态机；`sid` 唯一 |
| `end_ts` 不得小于 `start_ts + 1` | `close_session` / `close_dangling` 使用 `MAX(?, start_ts + 1)` |
| 进行中会话不出现在上传队列 | `pending_sessions` 只取 `end_ts > 0` |
| `uploaded` 只在上传成功后置 1 | `Uploader` 收到 2xx 后才调用 `mark_uploaded` |
| 强杀残留会被补结算 | 启动时 `close_dangling(last_heartbeat)` |
| 报表不虚增进行中会话 | `reporter.collect` 在心跳超过 120 秒未更新时，把 `end_ts=0` 夹到心跳时刻 |

### 3.5 关键查询

待上传队列（每批最多 `batch_size`，默认 500）：

```sql
SELECT id, start_ts, end_ts, app, title, category, device_id
FROM sessions
WHERE uploaded = 0 AND end_ts > 0
ORDER BY id
LIMIT ?;
```

与某天有重叠的会话：

```sql
SELECT id, start_ts, end_ts, app, title, category
FROM sessions
WHERE start_ts < ?      -- 次日 00:00
  AND (end_ts = 0 OR end_ts > ?)   -- 当天 00:00
ORDER BY start_ts;
```

待上传计数：

```sql
SELECT COUNT(*) FROM sessions WHERE uploaded = 0 AND end_ts > 0;
```

清空数据（保留 `meta`，`device_id` 不变）：

```sql
DELETE FROM sessions;
```

### 3.6 容量与保留

| 项 | 估算 |
|---|---|
| 会话行数 | 200 ~ 800 行/天（切换才结算，不是每 5 秒一行） |
| 单行体积 | 约 100~300 字节（标题截断 120 字符） |
| 一年体积 | < 5 MB |
| 保留策略 | 不自动删除；由用户执行 `app.py wipe` |

固定采样行方案（未采用）约 17,280 行/天，查询和存储都更重，因此选择会话式。

### 3.7 备份、恢复与迁移

- **在线备份**：优先用 SQLite 的 backup API；直接复制文件时 `infocollect.db` 可能还有
  `-wal` / `-shm` 旁文件，建议先正常退出采集（`stop.bat`）再复制整个目录。
- **恢复**：退出程序 → 用备份覆盖 `infocollect.db` → 启动。
- **迁移到另一台机器**：复制 `%APPDATA%\InfoCollect\` 即可；若要保留自启，需在新机器
  重新执行 `InfoCollect.exe autostart on`（注册表路径是绝对路径）。
- **测试隔离**：设置 `INFOCOLLECT_HOME` 指向临时目录，测试脚本不会碰真实数据。

---

## 4. 云端 PostgreSQL（Supabase，可选）

### 4.1 事实表 `public.sessions`

```sql
create table if not exists public.sessions (
    device_id    text        not null,
    id           bigint      not null,
    hostname     text        not null default '',
    device_label text        not null default '',
    start_ts     bigint      not null,
    end_ts       bigint      not null,
    app          text        not null default '',
    category     text        not null default '',
    title        text        not null default '',
    received_at  timestamptz not null default now(),
    constraint sessions_pkey primary key (device_id, id)
);
```

主键为什么是 `(device_id, id)`：`id` 是客户端 SQLite 自增，只在本机唯一；
两台电脑都会出现 `id = 1`，必须和设备标识组合才能全局唯一。

索引：

```sql
create index if not exists idx_sessions_start  on public.sessions (start_ts);
create index if not exists idx_sessions_device on public.sessions (device_id, start_ts);
```

### 4.2 本地到云端的字段映射

| 本地 `sessions` | 云端 `sessions` | 说明 |
|---|---|---|
| `device_id` | `device_id` | 主键组成部分 |
| `id` | `id` | 主键组成部分 |
| `start_ts` | `start_ts` | 原样上传 |
| `end_ts` | `end_ts` | 只上传已结算会话 |
| `app` | `app` | 原样 |
| `category` | `category` | 原样 |
| `title` | `title` | 仅当 `upload.include_title = true`；否则传空串 |
| `uploaded` | —（不存） | 云端存在即代表已上传 |
| — | `hostname` | 客户端补充 `socket.gethostname()`（≤ 64 字符） |
| — | `device_label` | 配置中的显示名（≤ 40 字符） |
| — | `received_at` | 服务端默认 `now()` |

注意：即使不上传标题也必须传 `title: ""`，因为 `jsonb_to_recordset` 缺键会得到 NULL，
而云端 `title` 是 `not null`，否则会报 `23502`。

### 4.3 行级安全（RLS）与权限

```sql
alter table public.sessions enable row level security;

create policy "client can insert" on public.sessions
    for insert to anon with check (true);

create policy "owner can read" on public.sessions
    for select to authenticated using (true);

revoke all on public.sessions from anon;
grant insert on public.sessions to anon;

revoke all on public.sessions from authenticated;
grant select on public.sessions to authenticated;
```

| 角色 / 对象 | SELECT | INSERT | UPDATE | DELETE | 说明 |
|---|---|---|---|---|---|
| `anon`（桌面端 key） | 否 | 是（兼容旧客户端） | 否 | 否 | key 会随 exe 分发，按「一定泄露」设计 |
| `authenticated`（手机登录用户） | 是 | 否 | 否 | 否 | 只读 |
| `push_sessions` 函数 | — | 以属主身份写入 | — | — | 调用者 `anon` 只有 EXECUTE |

威胁模型：anon key 泄露后，最坏结果是有人向表里灌垃圾数据（可清理），
**读不到任何记录、改不了、删不掉**。这是整个权限模型的底线，改 schema 时不能破坏。

### 4.4 视图

`v_daily`：手机端按天拿聚合，避免拉原始行。

```sql
create or replace view public.v_daily
with (security_invoker = true) as
select
    ((to_timestamp(start_ts) at time zone 'Asia/Shanghai')::date) as day,
    device_id,
    coalesce(nullif(device_label, ''), nullif(hostname, ''), device_id) as device_name,
    app,
    category,
    sum(end_ts - start_ts)::bigint as seconds,
    count(*)::int                  as segments
from public.sessions
where end_ts > start_ts
group by 1, 2, 3, 4, 5;
```

`v_devices`：手机端设备下拉框与「最近活跃」展示。

```sql
create or replace view public.v_devices
with (security_invoker = true) as
select
    device_id,
    max(coalesce(nullif(device_label, ''), nullif(hostname, ''), device_id)) as device_name,
    min(start_ts) as first_seen,
    max(end_ts)   as last_seen,
    count(*)::int as sessions
from public.sessions
group by device_id;
```

关键点：

- `security_invoker = true` 让视图以调用者身份执行，RLS 继续生效；不加会以属主身份运行，等于绕过 RLS。
- 时区固定 `Asia/Shanghai`，改时区需要同时改视图与手机端展示逻辑。
- **已知近似**：跨越午夜的会话整段算在开始日；本地 `reporter.py` 按重叠时长精确切分。

### 4.5 上报函数 `push_sessions`

```sql
create or replace function public.push_sessions(rows jsonb)
returns int
language plpgsql
security definer
set search_path = public
as $$ ... $$;
```

行为：

1. 用 `jsonb_to_recordset` 把裸数组展开为行；
2. `insert ... on conflict (device_id, id) do nothing`；
3. 返回实际写入行数（`row_count`）。

为什么需要 `security definer`：

- 客户端想表达「重复就跳过」，PostgREST 的 `Prefer: resolution=ignore-duplicates`
  会翻译成 `ON CONFLICT DO NOTHING`，这需要 SELECT 权限；而 `anon` 按设计没有 SELECT。
- 函数以属主身份执行，`ON CONFLICT` 所需权限由属主提供；调用者仍然只能「通过函数写」，
  读不到、改不了、删不掉。
- `set search_path = public` 不能省，否则调用者可改 `search_path` 指向别的 schema，形成提权后门。

权限：

```sql
revoke all on function public.push_sessions(jsonb) from public;
grant execute on function public.push_sessions(jsonb) to anon;
```

---

## 5. 上报协议与事务边界

### 5.1 两种 payload

Supabase（当前线上使用）：

```json
{ "rows": [ { "device_id": "...", "id": 12, "hostname": "...", "device_label": "...",
              "start_ts": 1793339677, "end_ts": 1793341477, "app": "pycharm64.exe",
              "category": "编码", "title": "" } ] }
```

自建服务端（`provider = generic`）：

```json
{ "client": "InfoCollect/0.3", "device_id": "...", "sent_at": 1793343678,
  "sessions": [ ... ] }
```

### 5.2 一致性模型

```
读取 pending（uploaded=0, end_ts>0）
      ↓
POST 一批（≤ batch_size）
      ↓ 2xx?
   ├─ 是 → UPDATE uploaded=1（并记录 last_upload_at/count）
   └─ 否 → 不动，下次重试
```

- 投递语义：至少一次（可能因响应超时而重发）。
- 云端：`(device_id, id)` 主键 + `on conflict do nothing` → 幂等。
- 结果：不重不漏；重复推送时函数返回 0，客户端仍视为成功并标记 uploaded，避免无限重推。

### 5.3 批量与超时

| 参数 | 默认 | 上限 / 下限 |
|---|---|---|
| `batch_size` | 500 | ≥ 1；受服务端请求体大小限制时再下调 |
| `timeout_seconds` | 10 | 1~60；关机推送强制 `min(timeout, 2)` |
| `interval_hours` | 4 | 代码强制 ≥ 60 秒 |

---

## 6. 安全与隐私

| 项 | 做法 |
|---|---|
| 本机库位置 | `%APPDATA%`，默认仅当前用户可读 |
| 标题 | 默认采集；可整体关闭；默认不随上报发送；只存代表标题 |
| 云端密钥 | 客户端只带 anon/publishable key；写库走受控函数；RLS 兜底 |
| 删除能力 | 客户端与手机端都没有 update/delete 权限 |
| 数据清理 | 本地 `wipe`；云端需在 Dashboard 手动清理（没有开放删除接口） |
| 测试隔离 | `INFOCOLLECT_HOME` 指向临时目录 |

---

## 7. 变更流程

### 7.1 本地 SQLite

1. 修改 `win/store.py` 的 `SCHEMA`；新表/新索引用 `IF NOT EXISTS`。
2. 新增列：`CREATE TABLE IF NOT EXISTS` 不会给老库加列，需要在 `Store.__init__` 里
   用 `PRAGMA table_info` 检查后 `ALTER TABLE ... ADD COLUMN`（当前尚未使用）。
3. 新增 `meta` 键不需要迁移，`get_meta` 会返回默认值。
4. 改完后运行 `py -3 -m py_compile win/*.py`，并用临时 `INFOCOLLECT_HOME` 跑一次采集验证。

### 7.2 云端 Supabase

1. 修改 `supabase/schema.sql`，保持**幂等**：`create table if not exists`、
   `drop policy if exists` + `create policy`、`create or replace`。
2. Dashboard → SQL Editor → 整段 Run；只改函数时可跑 `supabase/push_fn.sql`。
3. 验证：

```bash
cd win
py -3 -X utf8 app.py cloud --ping
py -3 -X utf8 app.py cloud --dry-run
py -3 -X utf8 app.py upload
```

4. 权限底线（改 schema 前必读）：anon 只 insert、authenticated 只 select、
   谁都没有 update/delete；上报必须走 `push_sessions`。

---

## 8. 已知限制

| 限制 | 影响 | 处理 |
|---|---|---|
| 云端跨午夜整段计入开始日 | 手机端某天时长可能偏多/偏少 | 以本地报表为准；需要精确时改视图按重叠切分 |
| 云端时区写死 `Asia/Shanghai` | 人在其他时区时 `day` 不对 | 同时改视图与手机端 |
| 没有 schema_version 迁移框架 | 字段变更需手工 | 单人项目，保持幂等 SQL + 手写 ALTER |
| WAL 旁文件 | 直接复制 db 可能丢最近写入 | 先停止采集再备份，或用 SQLite backup API |
| 云端没有删除接口 | 清空云端需手动 | 在 Supabase Dashboard 执行 `delete` |
| 单机 device_id 不可迁移 | 复制数据目录会带走旧 device_id | 属预期；新机器想独立标识就删 `meta.device_id` |
