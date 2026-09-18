-- Step 3: one line per table (rows and md5 of its sorted rows), then every sequence.
SELECT format('SELECT %L, count(*), md5(coalesce(string_agg(x::text, E''\n'' ORDER BY x::text COLLATE "C"), '''')) FROM %I x',
              table_name, table_name)
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name <> 'schema_migrations'
ORDER BY table_name
\gexec
SELECT 'sequence ' || sequencename, last_value FROM pg_sequences ORDER BY sequencename;
