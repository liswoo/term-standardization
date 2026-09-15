CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE IF NOT EXISTS domains (
 code text PRIMARY KEY, description text NOT NULL DEFAULT '', source text NOT NULL
);
-- ACTIVE/DEPRECATED plus the government 공통표준도메인 sheet's own columns (data
-- type/length/format/unit): DEPRECATED rows are kept, never deleted, so a term
-- already registered against a domain the standard later retires keeps a valid FK.
ALTER TABLE domains ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','DEPRECATED'));
ALTER TABLE domains ADD COLUMN IF NOT EXISTS data_type text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS data_length int;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS decimal_length int;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS storage_format text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS display_format text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS unit text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS domain_group text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS domain_classification text;
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
ALTER TABLE standard_terms ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','DEPRECATED'));
CREATE INDEX IF NOT EXISTS term_name_trgm ON standard_terms USING gin(normalized_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS term_synonyms ON standard_terms USING gin(normalized_synonyms);
CREATE INDEX IF NOT EXISTS term_tokens ON standard_terms USING gin(noun_tokens);
-- 표준단어(Standard Word) layer: the atomic units standard_terms are composed
-- from (e.g. "지사"+"분류"+"코드" -> "지사분류코드"). Matching an already-known
-- word during term decomposition is exact/normalized (1의미1단어 - a word IS its
-- name), but *finding whether a word already exists for a given meaning* (the
-- entry point for requesting a new word) is a different problem that needs
-- semantic search just like standard_terms - hence the embedding column below.
CREATE TABLE IF NOT EXISTS standard_words (
 id uuid PRIMARY KEY, name text NOT NULL, normalized_name text NOT NULL UNIQUE,
 english_abbr text NOT NULL, english_name text NOT NULL DEFAULT '',
 definition text NOT NULL DEFAULT '',
 is_format_word boolean NOT NULL DEFAULT false, domain_classification text NOT NULL DEFAULT '',
 synonyms text[] NOT NULL DEFAULT '{}', normalized_synonyms text[] NOT NULL DEFAULT '{}',
 forbidden_words text[] NOT NULL DEFAULT '{}',
 status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','DEPRECATED')),
 source text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE standard_words ADD COLUMN IF NOT EXISTS embedding vector(384);
ALTER TABLE standard_words ADD COLUMN IF NOT EXISTS embedding_model text;
CREATE INDEX IF NOT EXISTS word_name_trgm ON standard_words USING gin(normalized_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS word_synonyms ON standard_words USING gin(normalized_synonyms);
CREATE TABLE IF NOT EXISTS word_registration_preparations (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, assessment jsonb NOT NULL,
 requester text NOT NULL, conversation_id text NOT NULL, catalog_fingerprint text NOT NULL,
 status text NOT NULL DEFAULT 'AWAITING_CONFIRMATION' CHECK(status IN ('AWAITING_CONFIRMATION','SUBMITTED','CANCELLED')),
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS word_registration_requests (
 id uuid PRIMARY KEY, preparation_id uuid NOT NULL UNIQUE REFERENCES word_registration_preparations(id),
 word_name text NOT NULL, normalized_name text NOT NULL, definition text NOT NULL,
 english_abbr text NOT NULL, is_format_word boolean NOT NULL DEFAULT false,
 domain_classification text NOT NULL DEFAULT '',
 status text NOT NULL DEFAULT 'PENDING_REVIEW' CHECK(status IN ('PENDING_REVIEW','APPROVED','REJECTED')),
 requester text NOT NULL, conversation_id text NOT NULL, assessment jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS pending_word_name_unique ON word_registration_requests(normalized_name) WHERE status='PENDING_REVIEW';
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
-- A term whose name didn't fully decompose into known standard_words gets its
-- missing word submitted alongside it (see conversation.py's confirm_term/
-- _resume_or_finish_word_flow) - but that word isn't an official standard yet,
-- so the term must not sit in the same PENDING_REVIEW queue as a term ready for
-- review on its own merits. WAITING_FOR_WORD_APPROVAL marks that dependency;
-- word_registration.approve() promotes it to PENDING_REVIEW once the word is in.
ALTER TABLE registration_requests DROP CONSTRAINT IF EXISTS registration_requests_status_check;
ALTER TABLE registration_requests ADD CONSTRAINT registration_requests_status_check
    CHECK(status IN ('PENDING_REVIEW','WAITING_FOR_WORD_APPROVAL','APPROVED','REJECTED'));
ALTER TABLE registration_requests ADD COLUMN IF NOT EXISTS depends_on_word_request_id uuid REFERENCES word_registration_requests(id);
DROP INDEX IF EXISTS pending_name_unique;
CREATE UNIQUE INDEX IF NOT EXISTS pending_name_unique ON registration_requests(normalized_name)
    WHERE status IN ('PENDING_REVIEW','WAITING_FOR_WORD_APPROVAL');
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
