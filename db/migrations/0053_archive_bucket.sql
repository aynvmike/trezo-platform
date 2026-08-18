-- 0053 -- private storage bucket for the archive (2026-08-18)
--
-- Tier one of "nothing exists only on the server". The engine already
-- holds the service-role key, so this needs no new credential anywhere.
-- Private: it contains the full activity log and a copy of every book.

insert into storage.buckets (id, name, public)
values ('trezo-archive', 'trezo-archive', false)
on conflict (id) do nothing;

-- No RLS policies deliberately: the service role bypasses them, and
-- nothing else should ever read this bucket.

select 'archive bucket ready' as status;
