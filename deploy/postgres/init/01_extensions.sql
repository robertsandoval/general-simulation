-- Initialisation SQL — runs once when the container first starts.
-- (docker-entrypoint-initdb.d executes *.sql files in alphabetical order.)
--
-- The server must have been started with shared_preload_libraries = 'age'
-- (done via the compose command / OpenShift env) before this script runs.
--
-- Llama Stack owns the pgvector embedding tables at runtime — do NOT create
-- them here; just ensure the extension exists.

CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
