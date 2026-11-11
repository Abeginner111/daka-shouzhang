-- ===================================================================
-- 恋爱四年，想做的 100 件小事  ·  Supabase 初始化脚本
-- 用法：Supabase 控制台 → SQL Editor → New query → 整段粘贴 → Run
-- 只需执行一次。脚本可重复运行（策略先 drop 再 create），不会清数据。
-- ===================================================================
--
-- 【一次性配置清单】
--  1. supabase.com 新建项目（免费层：500MB 数据库 / 1GB 存储 / 无限 API 请求，
--     最多 2 个活跃项目；连续 7 天无请求会暂停，到控制台 Restore 即可，数据不丢）
--  2. 执行下面这段 SQL
--  3. Authentication → Providers → Email：关闭 Confirm email
--     （不关的话新注册要收确认邮件才能登录）
--  4. Authentication → URL Configuration：Site URL 填你的 Pages 地址
--     https://<用户名>.github.io/<仓库名>/
--  5. Project Settings → API：取 Project URL 和 publishable key
--     （旧版叫 anon key；绝对不要填 service_role / secret key，那个会绕过 RLS）
--     这两项已内置在 index.html 的 BUILTIN 里，正常打开页面即用，无需每次填写。
--     publishable key 本来就是设计成可公开的，放进公开仓库无妨——数据由 RLS 按账号隔离。
--     若以后换项目：页面「账号 → 更改云端连接配置」里改（只存本机浏览器，不写回仓库），
--     或直接改 index.html 里的 BUILTIN 两行后重新上传。
--  6. GitHub 新建 public 仓库 → 上传 index.html → Settings → Pages →
--     Source 选 Deploy from a branch / main / (root) → Save，等 1~2 分钟
--  7. 首次打开点「注册并初始化 100 件小事」；之后换设备只需登录同一账号，
--     不用再填连接配置（配置随页面走，登录态才跟浏览器走）
--
-- 【安全模型】登录账号就是数据隔离边界。RLS 保证每个账号只能读写自己的行。
-- 公开仓库里只有 HTML 和一个不带权限的 publishable key，别人拿到链接也看不到你的记录。
-- 不要把真实隐私内容写进 HTML 源码；所有打卡内容都在数据库里。
-- ===================================================================

create table if not exists public.love_items (
  user_id     uuid        not null references auth.users(id) on delete cascade,
  no          integer     not null check (no between 1 and 9999),
  title       text        not null default '',
  category    text        not null default '',
  status      text        not null default '想去做',
  done_date   date,
  mood        text,
  note        text        not null default '',
  photos      jsonb       not null default '[]'::jsonb,
  updated_at  timestamptz not null default now(),
  primary key (user_id, no)
);

-- 编号 1–9999：预置 001–100，页面新增卡片自动取「当前最大编号 + 1」。
-- 兼容早期建表时 1–100 的旧约束，可重复执行。
alter table public.love_items drop constraint if exists love_items_no_check;

create table if not exists public.love_config (
  user_id uuid primary key references auth.users(id) on delete cascade,
  cats    jsonb not null default '[]'::jsonb,
  moods  jsonb not null default '[]'::jsonb
);

create index if not exists love_items_user_idx on public.love_items (user_id, no);

alter table public.love_items  enable row level security;
alter table public.love_config enable row level security;

drop policy if exists "love_items_owner" on public.love_items;
create policy "love_items_owner" on public.love_items
  for all to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "love_config_owner" on public.love_config;
create policy "love_config_owner" on public.love_config
  for all to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- 2026-10-30 起 Supabase 新建表不再自动授予 Data API 权限，必须显式 grant，
-- 否则前端会看到 401 / "Could not find the table"。
grant usage on schema public to authenticated;
grant select, insert, update, delete on public.love_items  to authenticated;
grant select, insert, update, delete on public.love_config to authenticated;
