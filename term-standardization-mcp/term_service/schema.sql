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
-- 정부 공공데이터 공통표준 원본 xlsx(공통표준용어 시트)에는 있었지만 최초 임포트 때
-- 빠졌던 4개 컬럼(2026-09-18) - import_standard_catalog() 전용 읽기전용 정부 메타데이터.
-- 허용값/표현형식은 실측 결과 99%+ 소속 도메인 값과 동일(허용값 83/13,176건만 다르고
-- 그중 82건은 도메인 쪽이 아예 비어있는 예외, 표현형식은 71/13,176건 중 36건만 실제
-- 내용이 다름 - 나머지는 쉼표 서식 등 원본 데이터 입력 노이즈)이라 신청 단계에서 입력받지
-- 않음 - "표준 데이터 조회"에서 term 자체 값이 없으면 소속 도메인 값으로 대체해서 보여줌.
-- 행정표준코드명/소관기관명은 정부 표준 자체의 관리 메타데이터라 신청자가 알 수 있는
-- 정보가 아님 - 마찬가지로 조회 화면 표시 전용, registration_requests엔 컬럼 자체가 없음
-- (챗봇도 간편 입력 폼도 이 4개를 받지 않음 - 전부 import_standard_catalog()로만 채워짐).
ALTER TABLE standard_terms ADD COLUMN IF NOT EXISTS valid_values text;
ALTER TABLE standard_terms ADD COLUMN IF NOT EXISTS display_format text;
ALTER TABLE standard_terms ADD COLUMN IF NOT EXISTS administrative_code_name text;
ALTER TABLE standard_terms ADD COLUMN IF NOT EXISTS competent_agency text;
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
-- WAITING_FOR_DOMAIN_APPROVAL (2026-09-21) is the domain-side twin of the above,
-- set when confirm_term's word check passed but the term's chosen domain doesn't
-- exist yet (conversation.py's domain-request sub-flow) - kept as a separate status
-- rather than folding into WAITING_FOR_WORD_APPROVAL so existing word-dependency
-- code/data/UI didn't need touching. A term needing BOTH a new word and a new
-- domain in the same flow still only gets one status column - see registration.
-- submit()'s comment for which one wins and why it doesn't affect correctness.
ALTER TABLE registration_requests DROP CONSTRAINT IF EXISTS registration_requests_status_check;
ALTER TABLE registration_requests ADD CONSTRAINT registration_requests_status_check
    CHECK(status IN ('PENDING_REVIEW','WAITING_FOR_WORD_APPROVAL','WAITING_FOR_DOMAIN_APPROVAL','APPROVED','REJECTED'));
ALTER TABLE registration_requests ADD COLUMN IF NOT EXISTS depends_on_word_request_id uuid REFERENCES word_registration_requests(id);
-- A term can now depend on several new words at once (a multi-noun gap split into
-- separate word registrations - see naming.py's split_into_nouns), so the single-FK
-- column above is replaced by a many-to-many table; word_registration.approve() only
-- releases a term once every one of its dependency rows here is APPROVED.
CREATE TABLE IF NOT EXISTS registration_request_word_dependencies (
 registration_request_id uuid NOT NULL REFERENCES registration_requests(id),
 word_request_id uuid NOT NULL REFERENCES word_registration_requests(id),
 PRIMARY KEY(registration_request_id,word_request_id)
);
INSERT INTO registration_request_word_dependencies(registration_request_id,word_request_id)
    SELECT id,depends_on_word_request_id FROM registration_requests WHERE depends_on_word_request_id IS NOT NULL
    ON CONFLICT DO NOTHING;
ALTER TABLE registration_requests DROP COLUMN IF EXISTS depends_on_word_request_id;
DROP INDEX IF EXISTS pending_name_unique;
CREATE UNIQUE INDEX IF NOT EXISTS pending_name_unique ON registration_requests(normalized_name)
    WHERE status IN ('PENDING_REVIEW','WAITING_FOR_WORD_APPROVAL','WAITING_FOR_DOMAIN_APPROVAL');
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
-- Real login/session/role support. A signup is just another approval-queue row,
-- the same shape as registration_requests/word_registration_requests - only an
-- ADMIN can move it out of PENDING_APPROVAL (manage.py's create-admin bootstraps
-- the very first ADMIN, since a fresh DB has none yet to approve one).
CREATE TABLE IF NOT EXISTS users (
 id uuid PRIMARY KEY, username text NOT NULL UNIQUE, password_hash text NOT NULL,
 display_name text NOT NULL, team text NOT NULL DEFAULT '',
 role text NOT NULL DEFAULT 'MEMBER' CHECK(role IN ('ADMIN','MEMBER')),
 status text NOT NULL DEFAULT 'PENDING_APPROVAL' CHECK(status IN ('PENDING_APPROVAL','ACTIVE','SUSPENDED','REJECTED')),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
-- Opaque random session tokens (secrets.token_urlsafe), not JWTs - the same
-- "random ID row in Postgres with an expiry" shape registration_preparations/
-- word_registration_preparations already use for confirmation flows.
CREATE TABLE IF NOT EXISTS sessions (
 token text PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);

-- 도메인 신청(버튼 기반 직접 입력 폼, AI 챗봇 아님) - registration_preparations/
-- word_registration_preparations와 동일한 2단계 확인 패턴이지만, 대화가 아니라
-- 폼 제출 한 번으로 prepare+submit이 같은 요청 안에서 끝나므로 conversation_id는
-- "direct-form" 고정값만 씀.
CREATE TABLE IF NOT EXISTS domain_preparations (
 id uuid PRIMARY KEY, payload jsonb NOT NULL, assessment jsonb NOT NULL,
 requester text NOT NULL, conversation_id text NOT NULL, catalog_fingerprint text NOT NULL,
 status text NOT NULL DEFAULT 'AWAITING_CONFIRMATION' CHECK(status IN ('AWAITING_CONFIRMATION','SUBMITTED','CANCELLED')),
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS domain_requests (
 id uuid PRIMARY KEY, preparation_id uuid NOT NULL UNIQUE REFERENCES domain_preparations(id),
 code text NOT NULL, domain_group text NOT NULL, physical_name text NOT NULL DEFAULT '',
 data_type text NOT NULL, data_length int, decimal_length int,
 min_value text, max_value text, display_format text, source_classification text,
 valid_values text, default_value text, description text NOT NULL DEFAULT '',
 is_personal_info boolean NOT NULL DEFAULT false, personal_info_type text,
 protection_level text, is_encrypted boolean NOT NULL DEFAULT false, encryption_method text,
 mapping_table text, mapping_column text,
 request_reason text NOT NULL DEFAULT '',
 status text NOT NULL DEFAULT 'PENDING_REVIEW' CHECK(status IN ('PENDING_REVIEW','APPROVED','REJECTED')),
 requester text NOT NULL, conversation_id text NOT NULL, assessment jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS pending_domain_code_unique ON domain_requests(code) WHERE status='PENDING_REVIEW';

-- Added here (not alongside registration_requests above) because domain_requests
-- must exist first - a fresh database runs this whole file top to bottom once.
ALTER TABLE registration_requests ADD COLUMN IF NOT EXISTS depends_on_domain_request_id uuid REFERENCES domain_requests(id);

-- 승인 시 domain_requests의 상세 필드를 domains로 승격시키는 대상 컬럼들. 정부
-- 카탈로그 임포트로 채워지는 기존 컬럼들과 마찬가지로 전부 nullable - 신청 시점에
-- 다 채워지길 강제하지 않음. source_classification(신청서의 "출처구분")은 기존
-- domains.source(내부 출처 문자열 - 'GOV_COMMON_STANDARD_2025_11' 등)와 이름은
-- 비슷하지만 다른 개념.
ALTER TABLE domains ADD COLUMN IF NOT EXISTS physical_name text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS min_value text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS max_value text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS source_classification text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS valid_values text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS default_value text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS is_personal_info boolean NOT NULL DEFAULT false;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS personal_info_type text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS protection_level text;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS is_encrypted boolean NOT NULL DEFAULT false;
ALTER TABLE domains ADD COLUMN IF NOT EXISTS encryption_method text;

-- 표준 데이터 조회 통합 화면(용어/단어/도메인을 하나의 피드로 합쳐 최신순 정렬)에서
-- 다른 두 테이블처럼 정렬 기준으로 쓰기 위함. 카탈로그 임포트로 채워진 기존 행은
-- 이 컬럼이 없었으므로 DEFAULT now()로 채워짐(배포 시점에 일괄 today로 찍히는
-- 1회성 부작용 - 버그 아님).
ALTER TABLE domains ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

-- 가상 운영 데이터 - 실제 개인정보 아님, 전부 합성값(SYNTHETIC_MOCKOPS_NOT_REAL).
-- "개인정보여부" 체크박스가 실제로 뭔가를 가리키게 하려면 메타데이터 카탈로그
-- 바깥에 그 "실제 데이터"에 해당하는 대상이 있어야 하므로 존재한다. manage.py
-- seed-mockops로 채워짐.
CREATE TABLE IF NOT EXISTS mockops_customers (
 id uuid PRIMARY KEY, name text NOT NULL, resident_number text NOT NULL,
 phone text NOT NULL, email text NOT NULL, address text NOT NULL,
 source text NOT NULL DEFAULT 'SYNTHETIC_MOCKOPS_NOT_REAL', created_at timestamptz NOT NULL DEFAULT now()
);

-- 도메인 하나가 여러 운영 테이블/컬럼에 쓰일 수 있어(예: 주민등록번호가 여러 테이블에
-- 있을 수 있음) 다대다로 둔다. table_name/column_name은 term_service/mock_operations.py의
-- ALLOWLISTED_MOCKOPS_TABLES로 반드시 재검증됨 - SQL identifier를 동적으로 조립하는
-- 코드라 여기 값이 임의 문자열이면 안 됨.
CREATE TABLE IF NOT EXISTS domain_data_mappings (
 id uuid PRIMARY KEY, domain_code text NOT NULL REFERENCES domains(code),
 table_name text NOT NULL, column_name text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(domain_code, table_name, column_name)
);
