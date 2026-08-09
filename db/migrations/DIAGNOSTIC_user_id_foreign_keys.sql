-- DIAGNOSTIC (read-only, changes nothing).
--
-- NOTE: an information_schema version of this returns ZERO ROWS even
-- though the constraint exists -- those views filter by privilege and
-- hide constraints that reference the `auth` schema. pg_catalog does not
-- filter, so query it directly.
--
-- Purpose: find every public table whose column is bound to auth.users.
-- That set is exactly the set that cannot hold a synthetic "book" id,
-- and it therefore defines how large the owner/account split really is.

SELECT
  con.conrelid::regclass::text        AS table_name,
  a.attname                           AS column_name,
  con.confrelid::regclass::text       AS references_table,
  CASE con.confdeltype
    WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT'
    WHEN 'c' THEN 'CASCADE'   WHEN 'n' THEN 'SET NULL'
    WHEN 'd' THEN 'SET DEFAULT' END   AS on_delete
FROM pg_constraint con
JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
JOIN pg_attribute a
  ON a.attrelid = con.conrelid AND a.attnum = k.attnum
WHERE con.contype = 'f'
  AND con.connamespace = 'public'::regnamespace
  AND con.confrelid = 'auth.users'::regclass
ORDER BY 1, 2;
