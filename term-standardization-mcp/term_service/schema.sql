CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE IF NOT EXISTS domains (
 code text PRIMARY KEY, description text NOT NULL DEFAULT '', source text NOT NULL
);
CREATE TABLE IF NOT EXISTS standard_terms (
 id uuid PRIMARY KEY, name text NOT NULL, normalized_name text NOT NULL UNIQUE,
 definition text NOT NULL, domain text NOT NULL REFERENCES domains(code),
 synonyms text[] NOT NULL DEFAULT '{}', normalized_synonyms text[] NOT NULL DEFAULT '{}',
 noun_tokens text[] NOT NULL DEFAULT '{}', source text NOT NULL,
 embedding vector(384) NOT NULL, embedding_model text NOT NULL,
 english_abbr text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE standard_terms ADD COLUMN IF NOT EXISTS english_abbr text;
CREATE INDEX IF NOT EXISTS term_name_trgm ON standard_terms USING gin(normalized_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS term_synonyms ON standard_terms USING gin(normalized_synonyms);
CREATE INDEX IF NOT EXISTS term_tokens ON standard_terms USING gin(noun_tokens);
CREATE TABLE IF NOT EXISTS abbreviation_aliases (
 abbreviation text PRIMARY KEY, names text[] NOT NULL, source text NOT NULL
);
CREATE TABLE IF NOT EXISTS registration_preparations (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, assessment jsonb NOT NULL,
 requester text NOT NULL, conversation_id text NOT NULL, catalog_fingerprint text NOT NULL,
 status text NOT NULL DEFAULT 'AWAITING_CONFIRMATION' CHECK(status IN ('AWAITING_CONFIRMATION','SUBMITTED','CANCELLED')),
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS registration_requests (
 id uuid PRIMARY KEY, preparation_id uuid NOT NULL UNIQUE REFERENCES registration_preparations(id),
 term_name text NOT NULL, normalized_name text NOT NULL, definition text NOT NULL,
 domain text NOT NULL, synonyms text[] NOT NULL DEFAULT '{}', english_abbr text,
 status text NOT NULL DEFAULT 'PENDING_REVIEW' CHECK(status IN ('PENDING_REVIEW','APPROVED','REJECTED')),
 requester text NOT NULL, conversation_id text NOT NULL, assessment jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE registration_requests ADD COLUMN IF NOT EXISTS english_abbr text;
CREATE UNIQUE INDEX IF NOT EXISTS pending_name_unique ON registration_requests(normalized_name) WHERE status='PENDING_REVIEW';
CREATE TABLE IF NOT EXISTS comparison_cache (
 fingerprint text PRIMARY KEY, result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
-- Vectorized standard_guide.md, chunked by section. Backs the guideline
-- compliance check (RAG over the actual guide document, not a hardcoded
-- word blacklist) that runs during term registration.
CREATE TABLE IF NOT EXISTS guideline_chunks (
 id uuid PRIMARY KEY, section text NOT NULL UNIQUE, content text NOT NULL,
 embedding vector(384) NOT NULL, embedding_model text NOT NULL, source text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS conversation_state (
 conversation_id text NOT NULL, requester text NOT NULL, revision int NOT NULL DEFAULT 0,
 state jsonb NOT NULL DEFAULT '{}', updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(conversation_id, requester)
);
