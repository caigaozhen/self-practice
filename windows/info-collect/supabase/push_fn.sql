-- ============================================================
--  push_fn.sql —— 只补"上报函数"这一段
--  适用：已经跑过旧版 schema.sql（表、视图都有了），只缺 push_sessions。
--  用法：Supabase Dashboard → SQL Editor → 整段粘贴 → Run
--  可重复执行（create or replace + revoke/grant 都是幂等的）
-- ============================================================


-- ------------------------------------------------------------
-- 上报入口：security definer 函数
-- ------------------------------------------------------------
-- 为什么不让客户端直接 insert：
--   客户端要表达"重复就跳过"，只能用 Prefer: resolution=ignore-duplicates，
--   而 PostgREST 把它翻译成 `ON CONFLICT DO NOTHING`——这条语句需要 SELECT 权限。
--   anon 按设计只有 insert 没有 select，于是被 401 挡掉。
--
--   security definer 让函数以属主（postgres）身份执行，ON CONFLICT 需要的读权限
--   由属主提供；调用者 anon 依然只能"通过这个函数写"，读不到任何一行。
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

-- 新建函数默认对 public 可执行，必须先收回，再单独授权给 anon
revoke all on function public.push_sessions(jsonb) from public;
grant execute on function public.push_sessions(jsonb) to anon;

-- 让 PostgREST 立刻刷新缓存，否则刚建完就调用会报
-- PGRST202 "Could not find the function ... in the schema cache"
notify pgrst, 'reload schema';
