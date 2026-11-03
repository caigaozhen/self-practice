# supabase · 云端

存一份电脑上报上来的会话记录，让手机能看。**它是副本，不是唯一一份**——本地 SQLite 才是源。

## 已有项目

| 项 | 值 |
|---|---|
| 项目地址 | `https://krejgoouimoscaijevd.supabase.co` |
| 区域 | ap-south-1（孟买），跨境访问，上报超时已设成 10 秒 |
| 表 | `sessions`（主键 `device_id + id`） |
| 视图 | `v_daily`（按天聚合）、`v_devices`（设备清单） |

## 五步接通（约 5 分钟）

### 1. 建表

Dashboard → 左侧 **SQL Editor** → 新建查询 → 把 `schema.sql` 整个粘进去 → **Run**。

脚本包含三样东西：`sessions` 表 + RLS 策略、`v_daily`/`v_devices` 两个视图、
以及客户端真正调用的 `push_sessions(jsonb)` 函数。脚本幂等，以后再跑也不会报错、不会重复建。

> 如果你之前跑过**旧版** `schema.sql`（还没有 `push_sessions`），只补函数就行：
> 单独跑一次 `push_fn.sql`。判断有没有缺：
> `app.py cloud --ping` 报 `PGRST202 Could not find the function` 就是缺这段。

### 2. 创建一个登录用户（手机端读数据要用）

Dashboard → **Authentication** → **Users** → **Add user** → **Create new user**

- Email 填你的邮箱，Password 自己定
- **勾上 "Auto Confirm User"**，否则首次登录会卡在"邮箱未验证"

这个账号只用来在手机上登录，不会发任何邮件。

### 3. 取 anon key

**Project Settings** → **API** → 复制 **`anon` `public`** 那一长串（`eyJhbGciOi...`）。

> 为什么敢把 anon key 放在手机浏览器里：`schema.sql` 里 `anon` 角色**只有 insert 权限，没有 select / update / delete**。
> 即使 key 泄露，别人最多往你表里灌垃圾数据，读不到、也改不了你的记录。

### 4. Windows 端开启上报

改 `%APPDATA%\InfoCollect\config.json` 的 `upload` 段（也可以走 `app.py ui` 界面，但界面里没有 provider 下拉框，建议直接改文件）：

```json
"upload": {
    "enabled": true,
    "provider": "supabase",
    "endpoint": "https://krejgoouimoscaijevd.supabase.co",
    "token": "<粘贴 anon key>",
    "include_title": false,
    "interval_hours": 4,
    "on_shutdown": true,
    "timeout_seconds": 10,
    "batch_size": 500
}
```

`endpoint` 只填项目根地址就行，程序会自动补成 `/rest/v1/rpc/push_sessions`（调用数据库函数，不是直接写表）。

改完不用重启采集进程——托盘每 30 秒检查一次配置文件，会自动热加载。

### 5. 验证

```bash
cd win

# 配置对不对、能不能连上
py -3 -X utf8 app.py cloud --ping

# 看要发什么（不真发）
py -3 -X utf8 app.py cloud --dry-run

# 真发一次
py -3 -X utf8 app.py upload
```

然后到 Dashboard → **Table Editor** → `sessions`，应该能看到行。或者 SQL Editor 跑：

```sql
select device_id, count(*), sum(end_ts - start_ts) as seconds
from sessions group by 1;
```

最后在手机打开 `mobile/index.html`，填地址 + anon key + 第 2 步的邮箱密码，就能看到数据。

## 权限模型（整个方案最关键的一段）

```
anon（桌面客户端 / 泄露的 key）  → 只 execute push_sessions(jsonb)（函数内部 insert）
authenticated（手机登录后）      → 只 select
update / delete                  → 谁都不给
```

三点设计考虑：

1. **桌面端只需写**，不需要读云端 —— 所以不给 select
2. **会话结算后不可变** —— 所以不需要 update，重推靠函数里的 `on conflict (device_id, id) do nothing` 天然幂等
3. **手机端走登录** —— 因为 RLS 的 `authenticated` 策略是唯一能安全「只让你自己读」的办法

`revoke all ... then grant insert` 这两行的顺序不能反：Supabase 给 `anon` 的默认权限是全部，不先 revoke 光加 grant 等于没限制。

## 为什么上报走函数而不是直接写表

客户端要的是「重复就跳过」。直接 `POST /rest/v1/sessions` 表达这个语义只有一条路：
`Prefer: resolution=ignore-duplicates`，而 PostgREST 把它翻译成 `ON CONFLICT DO NOTHING`——
**这条语句需要 SELECT 权限**，anon 按设计没有 select，于是被 401 挡掉。

改走 `security definer` 函数后：

| | 直接写表 | 走 push_sessions 函数 |
|---|---|---|
| 重复推送 | 401（缺 SELECT） | 正常跳过，返回 0 |
| anon 权限 | insert | 只有 execute |
| 能否读数据 | 不能 | 不能（函数里只有 insert） |
| 是否能被提权 | — | `set search_path = public` 已堵住 |

函数里的 `set search_path = public` 不能省：security definer 不定 search_path 时，
调用者可以改自己的 search_path 把表名指到别的 schema，等于留了个提权后门。

## 踩过的坑（报错 → 原因 → 处理）

| 现象 | 原因 | 处理 |
|---|---|---|
| `401` + `permission denied for table sessions` | 用 `Prefer: ignore-duplicates` 直写表，PostgREST 翻译成 `ON CONFLICT DO NOTHING`，需要 SELECT，anon 没有 | 改走 `push_sessions` 函数（本项目的做法） |
| `GET /rest/v1/` 返回 401 `Secret API key required` | 新版 Supabase 的 OpenAPI 根只认 secret key，**publishable key 报这个是正常的** | 别拿它判断健康度，改用 `POST {"rows": []}` |
| `PGRST202 Could not find the function ... schema cache` | 函数没建，或建完 PostgREST 还没刷新 | 跑 `push_fn.sql`；末尾的 `notify pgrst, 'reload schema'` 负责刷新 |
| `23502 null value in column "title"` | `jsonb_to_recordset` 遇到**缺键**给 NULL，而 `title` 是 not null | 客户端保证一定带 `title`（不采就传空串），函数里另有 `coalesce` 兜底 |

## 免费版要注意

| 项 | 说明 |
|---|---|
| 容量 | 500MB。按每天 600 行、每行约 100 字节，约 **20 年**。不是问题 |
| 暂停 | 连续 7 天无活动会暂停（HTTP 540）。我们每 4 小时推一次，不会触发 |
| 恢复 | 暂停后数据还在，Dashboard 点 Resume 几分钟回来；暂停超 90 天可下载逻辑备份 |
| 备份 | **免费版没有自动备份**，所以别把它当唯一副本 |
| 延迟 | 节点在孟买，跨境 TLS 握手 + POST 偶尔超时，失败就留到下次，不丢数据 |

## 常用查询

```sql
-- 今天各分类时长（分钟）
select category, round(sum(end_ts - start_ts) / 60.0) as minutes
from sessions
where start_ts >= extract(epoch from date_trunc('day', now() at time zone 'Asia/Shanghai'))::bigint
group by 1 order by 2 desc;

-- 每台设备最后一次上报（判断哪台机器掉线了）
select device_id, max(coalesce(nullif(device_label,''), hostname, device_id)) as name,
       to_timestamp(max(received_at)) as last_upload
from sessions group by 1;

-- 异常长会话（超过 3 小时，通常意味着某处没停表）
select * from sessions where end_ts - start_ts > 10800 order by start_ts desc limit 20;
```
