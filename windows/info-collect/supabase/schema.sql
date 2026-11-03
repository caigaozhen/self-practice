-- ============================================================
--  InfoCollect · Supabase 建表脚本
--  用法：Supabase Dashboard → SQL Editor → 整段粘贴 → Run
--  可重复执行（幂等），改完再跑一次也没事
-- ============================================================


-- ------------------------------------------------------------
-- 1. 主表：一条记录 = 某台设备上的一段连续工作
-- ------------------------------------------------------------
-- 为什么主键是 (device_id, id) 而不是 id：
--   id 是客户端 SQLite 的自增主键，只在本机唯一。
--   两台电脑都会出现 id=1，所以必须带上设备标识才能全局唯一。
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

-- 报表按天查、按设备查，各给一个索引
create index if not exists idx_sessions_start on public.sessions (start_ts);
create index if not exists idx_sessions_device on public.sessions (device_id, start_ts);


-- ------------------------------------------------------------
-- 2. 行级安全：客户端只写、不给读
-- ------------------------------------------------------------
-- 这是整个方案里最重要的一段。
-- 桌面客户端的 anon key 会被打进 exe，PyInstaller 的包能被反编译，
-- 所以必须假设"key 一定会泄露"。泄露后能造成什么后果，完全由这里决定：
--
--   insert 给 anon   → 他能往你表里灌垃圾数据（可接受，清掉就行）
--   select 不给 anon → 他读不到你的任何记录（关键）
--   update/delete 都不给 → 他改不了、删不掉你的数据
--
-- 手机端要走登录（authenticated 角色）才能读，见第 3 段。
alter table public.sessions enable row level security;

drop policy if exists "client can insert" on public.sessions;
create policy "client can insert" on public.sessions
    for insert
    to anon
    with check (true);

drop policy if exists "owner can read" on public.sessions;
create policy "owner can read" on public.sessions
    for select
    to authenticated
    using (true);

-- RLS 只是"行级"过滤，表级权限还得单独给。
-- 注意顺序：先 revoke all 再单独 grant，否则 Supabase 的默认权限会让 anon 持有全部权限。
revoke all on public.sessions from anon;
grant insert on public.sessions to anon;

revoke all on public.sessions from authenticated;
grant select on public.sessions to authenticated;

-- anon / authenticated 都不许 update/delete（默认就没有，这里显式写一遍当文档）


-- ------------------------------------------------------------
-- 3. 聚合视图：手机端一次请求拿一天的数，不用拉原始行
-- ------------------------------------------------------------
-- 时区写死 Asia/Shanghai。人在别的时区就改这一处，两处都要改。
-- security_invoker = true 很关键：让视图以"调用者"身份执行，
-- 这样 RLS 依然生效。不加的话视图会以 owner 身份跑，等于绕过 RLS 把数据全暴露。
--
-- 已知近似：跨越午夜的那一段整段算在开始那天。
-- 本地报表（reporter.py）是按重叠时长精确切分的，云端这个视图没做那么细。
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

revoke all on public.v_daily from anon;
grant select on public.v_daily to authenticated;


-- 设备清单，手机端"按设备切换"的下拉框用它
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

revoke all on public.v_devices from anon;
grant select on public.v_devices to authenticated;


-- ------------------------------------------------------------
-- 4. 上报入口：一个 security definer 函数（客户端实际调的就是它）
-- ------------------------------------------------------------
-- 为什么不让客户端直接 insert：
--   客户端要表达"重复就跳过"，只能用 Prefer: resolution=ignore-duplicates，
--   而 PostgREST 把它翻译成 `ON CONFLICT DO NOTHING`——这条语句需要 SELECT 权限。
--   anon 按上面的设计只有 insert，于是被 401 挡掉（真实踩过的坑）。
--
--   security definer 让函数以属主（postgres）身份执行，ON CONFLICT 需要的读权限
--   由属主提供；调用者 anon 依然只能"通过这个函数写"，读不到任何一行，
--   也改不了、删不掉（函数里根本没有 update/delete）。
--
-- set search_path = public 不能省：
--   security definer 函数若不定 search_path，调用者可以改自己的 search_path，
--   把函数里的表名指到别的 schema，等于留了个提权后门。
--
-- 返回值是实际写入行数：重复推送时返回 0，客户端据此区分"新写入"和"已存在"。
create or replace function public.push_sessions(rows jsonb)
returns int
language plpgsql
security definer
set search_path = public
as $$
declare
    n int;
begin
    insert into public.sessions
        (device_id, id, hostname, device_label, start_ts, end_ts, app, category, title)
    select device_id, id,
           coalesce(hostname, ''), coalesce(device_label, ''),
           start_ts, end_ts,
           coalesce(app, ''), coalesce(category, ''), coalesce(title, '')
    from jsonb_to_recordset(rows) as x(
        device_id    text,
        id           bigint,
        hostname     text,
        device_label text,
        start_ts     bigint,
        end_ts       bigint,
        app          text,
        category     text,
        title        text
    )
    on conflict (device_id, id) do nothing;

    get diagnostics n = row_count;
    return n;
end;
$$;

-- 新建函数默认对 public 可执行，必须先收回，再单独授权给 anon。
-- 表级那个 insert 权限保留着，是为了兼容还没升级的旧客户端；新客户端用不到它。
revoke all on function public.push_sessions(jsonb) from public;
grant execute on function public.push_sessions(jsonb) to anon;


-- ------------------------------------------------------------
-- 5. 自检：跑完可以执行这段确认配置对不对
-- ------------------------------------------------------------
-- 期望结果：4 行 policy，anon 只有 insert，authenticated 只有 select
-- select tablename, policyname, cmd, roles
-- from pg_policies where schemaname = 'public' and tablename = 'sessions';
--
-- 期望结果：只有 anon=X（execute），没有别的角色拿到权限
-- select proname, proacl from pg_proc where proname = 'push_sessions';


-- ------------------------------------------------------------
-- 6. 让 PostgREST 立刻重新读一遍 schema
-- ------------------------------------------------------------
-- 刚建完函数就去调用，可能报 PGRST202 "Could not find the function ... in the schema cache"，
-- 因为 PostgREST 缓存了表/函数的清单。这条通知让它马上刷新，省得等或手动重启。
notify pgrst, 'reload schema';
