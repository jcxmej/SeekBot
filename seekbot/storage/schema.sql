CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS jobs (
    job_key TEXT PRIMARY KEY,
    job_id TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    hr_name TEXT NOT NULL DEFAULT '',
    hr_email TEXT NOT NULL DEFAULT '',
    hr_phone TEXT NOT NULL DEFAULT '',
    external_url TEXT NOT NULL DEFAULT '',
    search_url TEXT NOT NULL DEFAULT '',
    keyword TEXT NOT NULL DEFAULT '',
    role_key TEXT NOT NULL DEFAULT '',
    selected_resume_role TEXT NOT NULL DEFAULT '',
    resume_path TEXT NOT NULL DEFAULT '',
    quick_apply BOOLEAN NOT NULL DEFAULT FALSE,
    compatibility_score DOUBLE PRECISION,
    compatibility_threshold DOUBLE PRECISION,
    matched_keywords TEXT NOT NULL DEFAULT '',
    missing_keywords TEXT NOT NULL DEFAULT '',
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    external BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE UNIQUE INDEX IF NOT EXISTS jobs_url_idx ON jobs (url);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status);
CREATE INDEX IF NOT EXISTS jobs_timestamp_idx ON jobs (timestamp DESC);

CREATE TABLE IF NOT EXISTS qa_memory (
    memory_key TEXT PRIMARY KEY,
    question_hash TEXT NOT NULL,
    normalized_question TEXT NOT NULL,
    question_text TEXT NOT NULL,
    has_options BOOLEAN NOT NULL DEFAULT FALSE,
    options TEXT NOT NULL DEFAULT '',
    options_signature TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL,
    answered_by TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    times_used INTEGER NOT NULL DEFAULT 1,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    embedding VECTOR(__VECTOR_DIMS__)
);

CREATE INDEX IF NOT EXISTS qa_memory_question_hash_idx ON qa_memory (question_hash);
CREATE INDEX IF NOT EXISTS qa_memory_verified_idx ON qa_memory (verified);
CREATE INDEX IF NOT EXISTS qa_memory_last_seen_idx ON qa_memory (last_seen DESC);
CREATE INDEX IF NOT EXISTS qa_memory_embedding_idx
ON qa_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

CREATE TABLE IF NOT EXISTS run_logs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS llm_logs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_kind TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    response TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS debug_runs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    job_url TEXT NOT NULL DEFAULT '',
    resume_role TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL DEFAULT '',
    options TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    raw_response TEXT NOT NULL DEFAULT '',
    parsed_response JSONB NOT NULL DEFAULT '{}'::jsonb,
    context JSONB NOT NULL DEFAULT '{}'::jsonb
);
