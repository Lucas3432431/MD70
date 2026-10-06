create table public.profiles (
  id uuid primary key,
  full_name text,
  phone text,
  address text,
  city text,
  pref_email boolean not null default true,
  pref_whatsapp boolean not null default true,
  referral_code text unique not null default substr(md5(gen_random_uuid()::text),1,8),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
grant select, insert, update on public.profiles to authenticated;
grant all on public.profiles to service_role;
alter table public.profiles enable row level security;
create policy "own profile read" on public.profiles for select to authenticated using (auth.uid() = id);
create policy "own profile insert" on public.profiles for insert to authenticated with check (auth.uid() = id);
create policy "own profile update" on public.profiles for update to authenticated using (auth.uid() = id) with check (auth.uid() = id);

create or replace function public.handle_new_user() returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, full_name) values (new.id, coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email,'@',1)));
  return new;
end; $$;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_user();

create table public.leads (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 2 and 120),
  whatsapp text not null check (char_length(whatsapp) between 8 and 30),
  email text not null check (char_length(email) between 5 and 200),
  city text check (char_length(city) <= 100),
  capital_range text check (char_length(capital_range) <= 60),
  message text check (char_length(message) <= 2000),
  referral_code text check (char_length(referral_code) <= 20),
  source text not null default 'site',
  created_at timestamptz not null default now()
);
grant insert on public.leads to anon, authenticated;
grant all on public.leads to service_role;
alter table public.leads enable row level security;
create policy "anyone can submit lead" on public.leads for insert to anon, authenticated with check (true);