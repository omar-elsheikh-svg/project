create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  plan text not null default 'free' check (plan in ('free', 'premium')),
  reports_this_month integer not null default 0,
  usage_month text not null default to_char(now(), 'YYYY-MM'),
  stripe_subscription_id text
);

create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id) values (new.id)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

create table public.datasets (
  id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  filename text not null,
  insights jsonb not null,
  created_at timestamptz not null default now()
);

create table public.reports (
  id uuid primary key default gen_random_uuid(),
  dataset_id uuid not null references public.datasets(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  content text not null,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;
alter table public.datasets enable row level security;
alter table public.reports enable row level security;

create or replace function public.increment_report_usage(profile_id uuid, month_key text)
returns void language plpgsql security definer as $$
begin
  update public.profiles
  set reports_this_month = case when usage_month = month_key then reports_this_month + 1 else 1 end,
      usage_month = month_key
  where id = profile_id;
end;
$$;
