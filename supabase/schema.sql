-- BRAHMO: development-only persistent data schema.
-- Do not store patient-identifiable information.
--
-- Run this in the Supabase SQL editor (Project → SQL → New query).
-- Then add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to Streamlit secrets.

create table if not exists public.audit_events (
    id bigint generated always as identity primary key,
    event_type text not null,
    event_status text not null,
    details jsonb not null default '{}'::jsonb,
    app_version text not null default '0.1.0',
    created_at timestamptz not null default now()
);

create index if not exists idx_audit_events_created_at
    on public.audit_events (created_at desc);

create table if not exists public.source_versions (
    id bigint generated always as identity primary key,
    source_name text not null,
    version_label text not null,
    content_hash text,
    status text not null default 'DRAFT',
    created_at timestamptz not null default now(),
    unique (source_name, version_label)
);

-- Keep browser/public API roles from reading or modifying these tables.
alter table public.audit_events enable row level security;
alter table public.source_versions enable row level security;

revoke all on public.audit_events from anon, authenticated;
revoke all on public.source_versions from anon, authenticated;

-- Service role (used by the Streamlit backend via SUPABASE_SERVICE_ROLE_KEY)
-- bypasses RLS. Do not expose the service role key to the browser.
