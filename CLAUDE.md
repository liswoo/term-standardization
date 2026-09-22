# CLAUDE.md — 용어표준화 AI 에이전트

이 문서는 새 세션(에이전트든 사람이든)이 이 저장소에 처음 들어왔을 때 가장 먼저 읽는 문서입니다. **"무엇을 만들었는가"보다 "왜 이렇게 만들었는가"와 "다음에 뭘 조심해야 하는가"에 집중**합니다. "무엇이 있는가"(아키텍처 다이어그램, 모듈/MCP 도구 29개 전체 레퍼런스, 시간순 변경 이력)는 [docs/index.html](docs/index.html)을 보세요 — 브라우저로 `docs/index.html`을 열면 됩니다. 설치는 [SETUP.md](SETUP.md), Dify 자동화 내부 구조는 [term-standardization-mcp/AUTOMATION.md](term-standardization-mcp/AUTOMATION.md)를 보세요. 이 문서는 그것들을 대체하지 않고 연결합니다.

## 지금 상태: PoC → Product 전환 중

2026-09-08~11 사이 세션들에서 등록 대화 흐름의 핵심 기능(가이드라인 RAG 검사, 영문약어 추천, 정의 추천, 도메인 추천, UI 표/카드화)이 갖춰졌고, 2026-09-14 세션에서 **실제 정부 공공데이터 표준(data.go.kr)을 처음으로 DB에 적재**하고, 그 규모(용어 13,168건·단어 3,281건·도메인 126건)에서만 드러나는 스케일 버그 여러 개를 찾아 고쳤고, **표준단어 계층과 "의미 우선" 신규 단어 요청 플로우**를 새로 만들었습니다. 2026-09-16~17 세션에서는 **실제 로그인/세션/역할**(아래 절)과 **DATAVE 브랜드 적용**, **SaaS형 고정 레이아웃**(사이드바/상단바 고정, 표 본문만 스크롤), **용어사전·단어사전 검색창 통합**(이름·정의·요청자를 검색창 하나로), **도메인 신청(버튼 기반 직접 입력 폼) + 가상 운영 데이터/개인정보 매핑**(아래 절)이 추가됐습니다. **아직 PoC입니다** — 아래 "제품화 전 반드시 메워야 할 공백" 절을 먼저 읽으세요. `standard_terms`/`standard_words`/`domains`에는 이제 실제 정부 표준 데이터(`source='GOV_COMMON_STANDARD_2025_11'`)와 데모용 가상 데이터(`SYNTHETIC_SCENARIO_V1_NOT_OFFICIAL`, `data/scenario_catalog.json`)가 **공존**합니다 — `manage.py import-standard-catalog`가 전자를, `start.sh`의 자동 시딩이 후자를 채웁니다. 가이드라인 문서(`data/standard_guide.md`)는 여전히 전부 가상입니다.

## 시스템 구성

```
projects/
  dify/                     <- liswoo/dify 포크, 커밋 0df092d3c7(1.17.0)에 고정. Docker로 실행되는 별도 앱 플랫폼.
  term-standardization/     <- 이 저장소
    term-standardization-mcp/   <- MCP 서버(Python) + Postgres/pgvector. 업무 로직 전부 여기.
    term-standardization-ui/    <- 정적 프론트엔드(대시보드 + 채팅 패널). 순수 HTML/CSS/JS, 빌드 스텝 없음.
    tools/Caddyfile              <- UI(:8090)와 Dify API를 한 오리진으로 묶는 리버스 프록시.
```

- **dify 폴더는 "엔진"**, term-standardization은 "그 위에 얹은 우리 업무 로직 + 자동화 + 프론트"입니다. Dify 안의 앱/지식베이스/API 키/모델 자격증명은 설치본마다 새로 만들어지는 Dify 자체 DB 데이터라 설치본 간 이전이 안 됩니다 — `setup_dify.py`가 이 과정 전체를 자동화합니다(AUTOMATION.md).
- MCP 서버가 29개 도구를 노출하고, Dify Chatflow(`용어표준화-대화형`)가 사용자 메시지를 해석해 그 도구들을 호출합니다. **업무 판단과 저장의 기준은 항상 MCP**이고, Dify의 LLM 노드는 의도 해석과 답변 문장 생성만 담당합니다.
- 프론트엔드(`term-standardization-ui`)는 "용어표준화-대화형"(챗플로우) 외에 **"용어표준화-목록조회"**(단순 워크플로우, `build_list_terms_workflow.py`)도 씁니다 — 대시보드가 대화 상태 없이 한 번에 조회하는 읽기 전용 API로, `limit`/`offset`/`q` 입력을 받아 페이지네이션+검색을 지원합니다. 챗플로우와는 **별개의 Dify 앱**이라 배포도 별개입니다(`scripts/publish_list_terms_workflow.py` 한 번이면 끝 — 챗플로우 같은 3단계 아님). `q`는 이름/정의뿐 아니라 (검토 대기 요청에 한해) **요청자까지 OR로 매칭**합니다(2026-09-17). `requester` 파라미터 자체는 API 하위호환용으로 남아있지만 프론트는 더 이상 안 씁니다. 예전엔 용어사전/단어사전/도메인관리 3개 화면도 이 워크플로우를 같이 썼지만, 2026-09-17에 그 셋을 "표준 데이터 조회" 한 화면으로 합치면서 그쪽은 별개 경로인 `GET /admin/standard-data`(`term_service/unified_catalog.py`, Dify를 거치지 않는 순수 REST)로 옮겨졌습니다 — 대시보드만 계속 이 워크플로우를 씁니다.

## 대화 상태머신 (`term_service/conversation.py`)

`transition(state, action, ...)`이 순수 함수로 모든 단계 전이를 결정합니다. Dify는 사용자 메시지를 `{intent, value, confirmed}`로만 해석해서 넘기고, 실제 유효성 검사·중복 판정·저장은 전부 이 함수와 그 안에서 호출하는 모듈이 합니다.

**현재 단계 순서** (2026-09-10에 의도적으로 재배치됨):

```
propose_term → awaiting_term_confirm → confirm_term
  → (EXACT_MATCH/SYNONYM_MATCH) → existing_term_found  [종료]
  → (검토 대기 중복) → pending_request_found  [종료]
  → (형태소/가이드라인 위반) → awaiting_guideline_choice → propose_term로 재시도
  → (이름이 표준단어로 완전분해 안 됨) → awaiting_word_split_choice (하나로/여러 단어로 쪼갤지 선택, 2026-09-16 추가)
      → awaiting_word_meaning [신규 단어 요청 서브플로우, 아래 절 참고] (단어별로 반복) → 전부 완료 후 아래로 복귀
  → awaiting_definition (정의 제안/명확화 질문)
      → set_definition → awaiting_domain_choice (이제 이름+정의로 검색한 근거로 도메인 추천)
          → set_domain → registration.prepare() 호출 시점
              → (SAME_MEANING/GUIDELINE_VIOLATION/SYNONYM_CONFLICT) → definition_blocked  [종료]
              → awaiting_abbreviation (영문약어 제안)
                  → set_abbreviation → awaiting_confirm
                      → confirm_registration → submitted | registration_failed  [종료]
```

**왜 정의가 도메인보다 먼저인가**: 원래는 도메인을 먼저 물었습니다. 그런데 도메인 추천(`domain_usage()`)의 근거가 되는 비교군 검색이 그 시점엔 **용어명 하나뿐**이라 신호가 약했습니다. 실측: "주간식단"을 이름만으로 검색하면 "식단명"과의 코사인 유사도가 0.838(임계값 0.85 미만이라 탈락), 이름+정의로 검색하면 0.910으로 뛰어올랐습니다(SEMANTIC_THRESHOLD 절 참고). 그래서 **정의를 먼저 받고, 그 정의까지 포함한 검색으로 도메인을 추천**하도록 순서를 바꿨습니다(커밋 `9348aa2`). `registration.prepare()`(SAME_MEANING/구문 검증)는 이름+정의+도메인이 전부 모여야 호출 가능하므로 지금은 `set_domain`에서 실행됩니다 — 예전엔 `set_definition`에서 실행됐습니다. 이 순서를 다시 바꾸는 작업을 하게 되면 `edit_domain`/`edit_definition`의 리셋 범위(누가 무엇을 지우는지)도 반드시 같이 재점검하세요 — 지금은 "정의를 고치면 도메인 근거가 무효화되므로 도메인도 같이 지움", "도메인을 고쳐도 정의는 유지"로 되어 있습니다.

**프론트엔드는 이 순서와 무관합니다** — `app.js`의 카드 렌더러는 stage 이름과 그 stage가 들고 있는 state 필드만 보고 그리므로, 위 순서를 다시 바꿔도 프론트엔드는 손댈 필요가 없었습니다(실제로 이번 재배치에서 프론트 변경 0줄).

## 표준단어 계층 + "의미 우선" 신규 단어 요청 플로우 (2026-09-14)

**표준용어는 표준단어의 조합**입니다(예: "API명" = "API" + "명" → 약어 `API_NM`). 실제 정부 표준 500건 표본을 분해해보면 **99.8%가 `standard_words` 사전만으로 완전분해**됩니다 — 나머지 0.2%가 "사전에 없는 개념"이 섞인, 진짜 신규 단어가 필요한 경우입니다. `confirm_term`이 이름 확인 직후(가이드라인 검사 다음) `naming.segment_words()`로 이 완전분해를 체크하고, 실패하면 **`awaiting_word_split_choice`**로 분기해 사용자에게 "빠진 부분을 단어 하나로 등록할지, 여러 단어로 쪼갤지"부터 물은 뒤(2026-09-16 추가, `naming.unmatched_spans()`/`split_into_nouns()` — 예: "소리동굴"의 빠진 부분을 "소리동굴" 하나로 할지 "소리"+"동굴" 둘로 할지), 각 단어마다 **신규 단어 요청 서브플로우**(`awaiting_word_meaning`)를 순서대로 통과시킨 뒤 원래 용어 등록으로 복귀합니다(`state["resume_term"]`에 원래 진행 상황을 저장). 용어 하나가 **여러 단어 승인을 동시에 기다릴 수 있어서**, 예전의 단일 FK(`registration_requests.depends_on_word_request_id`)는 다대다 테이블 `registration_request_word_dependencies`로 바뀌었습니다 — `word_registration.approve()`는 그 용어의 의존 단어가 **전부** APPROVED여야 용어를 `WAITING_FOR_WORD_APPROVAL`에서 풀어줍니다.

**단어 등록은 이름이 아니라 의미가 입력입니다.** "이 개념을 이런 용도로 쓰고 있다"는 자유 설명(`propose_word`)을 받아서:
1. `search_words()`(단어 임베딩 기반 코사인 검색, `standard_terms`와 같은 메커니즘)로 의미가 비슷한 기존 단어를 찾고
2. `word_suggestion.suggest_word()`가 구조화 출력으로 **"기존 단어와 일치하는가"를 다른 무엇보다 먼저 판단**하도록 강제(`existing_word_match` 필드를 `ambiguous`/`name`보다 먼저 선언 — 아래 "작은 모델" 패턴과 동일한 트릭)한 뒤, 일치하면 재사용을 권하고, 애매하면 되묻고, 없으면 새 단어(이름+영문약어+정의)를 제안합니다.
3. 신규 단어는 용어와 완전히 대칭인 자체 심사 테이블(`word_registration_preparations`/`word_registration_requests`)에 `PENDING_REVIEW`로 쌓입니다 — 관리자가 CLI로 승인하기 전까지는(아래 미해결 이슈 1번) 사실상 즉시 쓰이는 것과 다름없이 대화가 진행됩니다.

**진입점이 두 개입니다**: (a) 위에서 설명한 **임베디드 진입**(용어 등록 중 자동 분기), (b) **독립 진입** — 사용자가 처음부터 "이런 개념을 단어로 추천해줘"라고 요청하면 `propose_word`가 `resume_term` 없이 같은 서브플로우를 타고, 끝나면 `word_reused`/`word_submitted`로 종료합니다(용어 등록으로 복귀하지 않음).

**알려진 한계 — 의도적으로 미룬 부분**: 기존 단어를 의미로 찾아서 재사용하기로 해도(예: "등본" 의미 → 기존 단어 "증명서"), **원래 용어명 자체는 바뀌지 않습니다.** "등기부등본"이라는 표기 안에는 "증명서"라는 글자가 없으므로, 재개된 용어 등록의 약어 추천 단계(`abbreviation.py`)는 여전히 문자열 기반 분해를 하고, 그 부분은 여전히 LLM이 즉석으로 약어를 지어냅니다. 즉 이 플로우는 **"이 개념에 이미 공식 표준이 있다"는 거버넌스 정보를 확실히 제공**하지만, 그걸 바탕으로 용어명 자체를 표준 단어로 리네이밍하도록 권하는 기능까지는 없습니다 — 다음 작업 후보로 남겨둡니다.

**단어 임베딩과 용어 임베딩은 용도가 다릅니다**: 용어 등록 중 "이름이 사전 단어와 일치하는가"는 `naming.segment_words()`로 **정확 문자열 매칭**만 합니다(1의미1단어 원칙 — 단어는 그 이름 자체가 식별자). 반면 신규 단어 요청 진입점의 "이 의미의 단어가 이미 있나" 탐색은 `search.search_words()`로 **의미 기반 코사인 검색**을 합니다(용어 검색과 동일 메커니즘). 같은 `standard_words` 테이블, 같은 임베딩 컬럼을 서로 다른 두 가지 목적으로 쓰는 것이니 혼동하지 마세요.

## 로그인 / 세션 / 역할 (2026-09-16)

`term_service/auth.py`(해싱·세션) + `admin_api.py`의 `/admin/auth/*` 라우트(신규 파일 아님, 기존 LLM 전환 API와 같은 파일)로 실제 인증을 구현했습니다. 새 설치에서 반드시 `manage.py create-admin`으로 최초 관리자를 만들어야 로그인 화면을 통과할 수 있습니다(SETUP.md 7단계) — 안 하면 아무도 못 들어갑니다.

- **비밀번호**: `hashlib.pbkdf2_hmac`(표준 라이브러리, 새 의존성 없음) + 랜덤 salt. `bcrypt`/`argon2` 같은 별도 패키지를 일부러 안 씀 — 이 프로젝트가 이미 `hashlib.sha256`을 카탈로그 fingerprint에 쓰는 것과 통일. 본인 비밀번호 변경 기능 있음(`/admin/auth/change-password`, 변경 시 다른 세션 전부 로그아웃).
- **세션**: JWT가 아니라 `sessions` 테이블(랜덤 토큰 + 만료시각) — `registration_preparations`가 이미 쓰는 "Postgres에 랜덤 ID 행 + 만료시각" 패턴 재사용. **httpOnly, SameSite=Lax 쿠키**로 전달(localStorage 토큰 아님) — `/admin/*`이 Caddy로 같은 오리진에 프록시되므로 프론트 코드에서 매 요청마다 헤더를 붙일 필요가 없고, `SameSite=Lax`가 모든 변경 라우트(POST)의 CSRF를 이미 막아서 별도 CSRF 토큰도 없습니다.
- **역할**: `users.role IN ('ADMIN','MEMBER')`. 신규 가입은 항상 `MEMBER`+`PENDING_APPROVAL`로 시작 — 승인은 관리자가 처리(`registration_requests`/`word_registration_requests`와 동일한 승인 큐 패턴을 회원가입에도 그대로 적용한 것). **마지막 남은 활성 관리자를 정지/강등하는 건 서버가 거부**합니다(`auth.active_admin_count()`) — 스스로 잠기는 걸 방지.
- **관리자 전용 UI (2026-09-17 회원관리를 별도 창으로 분리)**: 설정 화면엔 이제 "회원 관리"/"Dify 관리자 콘솔"/"LLM 모델 전환" 세 가지가 전부 관리자에게만 보이고, 회원 관리는 버튼을 누르면 같은 세션 쿠키를 공유하는 독립 창(`term-standardization-ui/members.html`)에서 처리합니다(자체적으로 `/admin/auth/me`로 관리자 여부를 다시 확인함 — 비관리자가 URL을 직접 열어도 안내 문구만 뜨고 API는 호출 안 됨).
- **`requester` 실화**: `term-standardization-ui/app.js`의 `CHAT_USER`가 이제 로그인한 실제 아이디입니다(예전엔 `"meta-system-ui"` 고정값) — 챗봇으로 신청한 용어/단어의 "요청자" 칸에 실제 로그인 아이디가 찍힙니다. 로그인 전 데이터(전부 `meta-system-ui`)는 소급 반영 안 됨.
- **범위 밖(의도적으로 안 함)**: 위 known-issue #2에 적었듯, 이 로그인은 **우리 프론트엔드 UI 자체**만 지킵니다 — Dify Chatflow/워크플로우 API를 프론트가 하드코딩된 키로 직접 호출하는 구조는 그대로라, 그 키를 아는 사람은 로그인 없이도 Dify에 직접 요청해 임의의 `requester` 값을 만들 수 있습니다. 진짜로 막으려면 Dify 호출 자체를 백엔드가 세션 검증 후 대신 호출하는 프록시로 바꿔야 합니다. 비밀번호 재설정/이메일 인증, 레이트리밋은 여전히 없습니다.

## 도메인 신청 (버튼 기반 직접 입력 폼) + 가상 운영 데이터 (2026-09-17)

레거시 메타관리시스템(국민건강보험 "b-well") 화면을 분석해서 만든 기능 — **AI 챗봇 대화가 아니라 사용자가 폼에 직접 입력해서 제출하는, 기존 현업 업무방식**입니다. 도메인은 이전까지 `manage.py import-standard-catalog`로만 채워지는 읽기 전용 참조 데이터였습니다. (같은 날 이후 용어/단어에도 같은 성격의 간편 입력 경로가 추가됐습니다 — 아래 "용어/단어 간편 입력 신청" 절 참고.)

- **아키텍처**: `domain_registration.py`가 `registration.py`/`word_registration.py`와 같은 `prepare()`/`submit()`/`approve()`/`reject()` 2단계 확인 패턴을 그대로 씁니다(도메인 코드 유일성만 확인, 임베딩/의미비교 없음). 다만 **대화가 아니라 폼 제출 한 번**이라 여러 턴에 걸친 사용자 이탈을 버틸 필요가 없으므로, `admin_api.py`의 `POST /admin/domain-requests` 하나가 prepare→submit(confirmed=True)을 같은 HTTP 요청 안에서 이어서 호출합니다 — MCP 챗봇 도구가 아니라 `/admin/*` REST 라우트로 구현(Dify를 아예 거치지 않음), 로그인/회원관리/LLM전환 스위치와 같은 위치.
- **승인은 여전히 CLI 전용**(`manage.py approve-domain <request_id>` / `reject-domain`) — 용어/단어와 동일한 수준. 결재선(다단계 승인)은 이번 범위 밖.
- **가상 운영 데이터**: "개인정보여부" 체크박스가 실제로 뭔가를 가리키게 하려면 메타데이터 카탈로그 바깥에 "실제 데이터"가 있어야 한다는 지적에 따라, `mockops_customers`(합성 고객 데이터, `SYNTHETIC_MOCKOPS_NOT_REAL`, `manage.py seed-mockops`로 시딩)와 `domain_data_mappings`(도메인 ↔ 운영 테이블/컬럼 매핑) 테이블을 추가했습니다. `term_service/mock_operations.py`의 `ALLOWLISTED_MOCKOPS_TABLES`가 유일한 진입점 — table_name/column_name은 SQL identifier라 파라미터 바인딩이 안 되므로, 이 화이트리스트 검사를 반드시 거친 값만 f-string으로 SQL에 들어갑니다(제거하면 안 되는 방어선). 개인정보로 지정된 도메인은 "도메인 관리" 화면에 배지가 붙고, 매핑이 있으면 "샘플 데이터 보기" 버튼으로 그 (가상) 데이터를 바로 조회할 수 있습니다.
- **범위 밖(의도적으로 안 함)**: 자동 개인정보 탐지/제안, 마스킹/접근통제(샘플 데이터는 합성값이라 그대로 노출), 신청구분(변경/삭제), 여러 건을 큐에 담았다가 한 번에 제출하는 배치 신청, 사진 속 "표준분류"(부서/업무영역 분류 — 우리 시스템은 단일 통합 카탈로그라 해당 개념 자체가 없음).

## "표준 데이터 조회" 신청 탭: 용어/단어/도메인 간편 입력 + (단어만) AI 대화 (2026-09-17, 용어 쪽 AI 대화 진입점은 2026-09-21 제거)

"표준 데이터 조회" 화면 상단에 조회/용어 신청/단어 신청/도메인 신청 4개 탭을 추가했습니다(독립 화면이던 "도메인 신청"도 이 탭으로 흡수). 용어/단어 신청 탭은 사용자가 **간편 입력(폼 한 번 제출)** 과 **AI와 대화하며 등록(기존 챗봇 재사용)** 중 하나를 고를 수 있습니다 — 둘 다 제공하기로 한 이유는, 도메인과 달리 용어/단어 등록은 원래부터 임베딩 기반 중복탐지·가이드라인 준수(LLM)·표준단어 완전분해가 필수로 얽혀 있어 챗봇 대화로만 가능했고, 그 다단계 판단을 버리면 품질 검증이 약해지기 때문입니다.

> **2026-09-21 갱신**: 용어 신청 탭의 "AI와 대화하며 등록" 카드/버튼은 **삭제**했습니다 — 헤더의 "+ 신규 용어 등록" 버튼이 같은 챗봇을 여는 중복 기능이었기 때문입니다. 대신 그 탭 안의 AI 추천을 켜고 끄는 토글이 들어갔습니다(아래 "용어 신청: AI 추천 ON/OFF 토글" 절). **단어 신청 탭은 그대로 두 경로**(간편 입력 + 대화로 등록)입니다 — 그쪽 버튼은 "단어를 등록할래요"로 헤더 버튼과 다른 흐름(단어 등록)에 들어가므로 중복이 아닙니다. 아래 두 번째 항목의 `term-ai-start-btn` 서술은 그 이전 상태의 기록입니다.

- **간편 입력의 정체**: 새 `POST /admin/term-requests`/`POST /admin/word-requests`(`admin_api.py`)는 `registration.py`/`word_registration.py`의 `prepare()`/`submit()`을 **그대로** 위임합니다 — 즉 챗봇 경로와 똑같은 임베딩+LLM 의미비교·가이드라인 검사를 거칩니다. 다단계 안내(재시도 유도, 정의 제안 등) 없이 첫 실패 사유를 그 자리에서 에러로 보여주는 점만 다릅니다. 용어 쪽은 새 `quick_registration.py`가 conversation.py의 confirm_term이 하던 **표준단어 gap 체크**(`naming.segment_words`/`unmatched_spans`)만 별도로 재현해서, 챗봇의 단어등록 서브플로우 없이는 처리 못 하는 이름을 `WORD_GAP_REQUIRES_REGISTRATION`으로 먼저 걸러냅니다(안 걸러내면 어떤 부분이 새 표준단어가 필요한지 아무도 모른 채 그냥 등록되어 버립니다). 단어 신청은 원래도 exact-match만 확인하는 단순 경로라 별도 모듈 없이 `word_registration.py`를 그대로 씀 — 도메인과 동급 난이도.
- **AI 대화 경로는 새로 만들지 않았습니다**: "대화로 등록 시작" 버튼은 그냥 기존 플로팅 챗봇을 열고(`openChat()`) `submitChatMessage("용어를 등록할래요")`(단어는 "단어를 등록할래요")를 대신 보낼 뿐입니다 — 이미 검증된 챗봇 플로우를 그대로 재사용. (용어 탭의 이 버튼은 2026-09-21에 제거됨 — 단어 탭의 `word-ai-start-btn`만 남음.)
- **아직 없는 것**: 용어/단어의 "내 신청 목록" 전용 뷰(도메인처럼) — "조회" 탭이 검토 대기 신청까지 이미 병합해서 보여주므로 중복 없이 생략. 간편 입력의 성공 경로 자체(용어)는 실제 LLM 호출이 있어 `RUN_LLM_TESTS=1` 없이는 자동 테스트하지 않음(기존 관례와 동일) — 브라우저로 직접 확인하세요.

## 정부 원본 xlsx의 용어별 누락 컬럼 + "도메인이 결정하는 값" 표시 원칙 (2026-09-18)

정부 공공데이터 공통표준 xlsx(`data/공공데이터 공통표준(2025.11월).xlsx`)의 3개 시트를 실측 대조해서 찾은 결과: **단어는 빠진 게 없었고**, **도메인은 스키마엔 있던 `valid_values` 컬럼을 `import_standard_catalog()`가 안 채우던 버그**(수정 완료, 129개 중 14개에 실제 값), **용어만 실제로 4개 컬럼이 DB 어디에도 없었습니다** — `valid_values`(허용값)/`display_format`(표현형식)/`administrative_code_name`(행정표준코드명)/`competent_agency`(소관기관명). 전부 `standard_terms`에 추가하고 `import_standard_catalog()`로 채웠습니다.

**처음엔 이 4개를 신청 폼에도 입력받게 만들었다가 뒤집었습니다.** 용어-도메인 쌍으로 허용값/표현형식을 다시 비교해보니(도메인 값과 "-"/타입 차이를 정확히 정규화해서 비교하는 게 중요했습니다 — 처음엔 비교 스크립트 버그로 표현형식 불일치를 71건이라고 했다가 705건으로 잘못 다시 셌던 적도 있습니다), 82/13,176건(허용값)을 제외하면 사실상 **도메인이 결정하는 값**이었고, 행정표준코드명·소관기관명은 애초에 신청자가 알 수 있는 정보가 아니었습니다. 그래서:

- **`registration_requests`엔 이 4개 컬럼을 추가하지 않았습니다** — 챗봇도 간편 입력 폼도 받지 않고, `standard_terms`는 오직 `import_standard_catalog()`로만 채워집니다(정부 원본 데이터 보존/표시 전용).
- 대신 **"도메인이 결정하는 값"을 신청 경로 전반에 보여주는 패턴**을 새로 만들었습니다: 새 `GET /admin/domains/{code}`(전체 도메인 스펙 반환) → 프론트 `fetchDomainDetail()`이 (1) 용어 신청 간편 입력 폼에서 도메인 선택 시 허용값/표현형식/저장형식을 읽기전용으로 자동 표시(제출 payload엔 미포함), (2) 챗봇의 등록완료 카드(`renderRegistrationCard`, 이제 async — `renderStructuredBlock`/`submitChatMessage`도 그래서 `await` 체인으로 바뀜)에서 대화 중엔 안 물어본 도메인 전체 스펙을 완료 시점에 한꺼번에 보여줍니다. **"대화 중엔 쓸데없는 정보를 묻지 않고, 완료 시점엔 전부 보여준다"**는 원칙입니다.
- "표준 데이터 조회"(`unified_catalog.py`)의 TERM 행은 `domains`를 LEFT JOIN해서 `valid_values`/`display_format`은 용어 자신의 값이 있으면 그걸(COALESCE, 정부 원본의 소수 예외 보존), 없으면(신규 신청 용어 전부 포함) 도메인 값을 대신 보여주고, `storage_format`/`data_type`/`data_length`/`decimal_length`/`unit`은 항상 도메인에서 가져옵니다(용어 자체엔 저장 안 함).
- **동의어(이음동의어) 챗봇 미수집 문제는 아직 미해결입니다** — `conversation.py`의 용어 등록 흐름이 동의어를 아예 안 물어보고 빈 배열로 등록하며, `registration.prepare()`의 `SYNONYM_CONFLICT` 검사도 그래서 챗봇 경로에선 전혀 안 탑니다. 새 대화 단계(intent) 추가 + Dify 챗플로우 재배포가 필요해 별도 작업으로 미룬 상태 — 다음에 다룰 때는 이 CLAUDE.md 절부터 먼저 읽으세요.

## 신규 도메인 의존성 처리 + 도메인 스펙 초안 모듈 + 챗봇 연결 (2026-09-21)

**챗봇에서 실제로 동작합니다** — `conversation.py`에 `request_new_domain`/`confirm_domain_spec`/`set_domain_pii` 인텐트와 `awaiting_domain_spec_clarify`/`awaiting_domain_spec_confirm`/`awaiting_domain_pii_choice`/`domain_spec_unavailable`/`domain_request_blocked` 단계를 추가하고, `build_chatflow.py`(CLASSIFY 규칙/RENDER 안내/퀵리플라이 버튼)·`app.js`(도메인 스펙 카드)까지 전부 연결한 뒤 실제 배포(`build_chatflow.py`→`dify_admin.py import`→`scripts/publish_chatflow.py`)까지 마치고 실 서비스로 curl이 아니라 진짜 `/v1/chat-messages` 스트리밍 호출로 처음부터 끝까지(용어명→단어 갭→새 도메인 거부→스펙 초안→개인정보 질문→약어→최종 등록→관리자 도메인 승인→용어 자동 승격) 검증했습니다.

지금 있는 걸로 풀 수 없던 문제: 챗봇 용어 등록 중 `awaiting_domain_choice`에서 사용자가 추천 도메인/기존 목록을 전부 거절하면(`UNRECOGNIZED_DOMAIN`), 지금은 그냥 막다른 길입니다. 용어가 그 자리에서 만들어질 신규 도메인 승인을 기다리게 하려면, **단어 의존성**(위 "표준단어 계층" 절)과 완전히 같은 문제 — "이 용어는 아직 확정 안 된 다른 무언가의 승인을 기다린다" — 를 도메인에도 풀어야 했습니다.

**의존성 배관**:
- `registration_requests.status`에 `WAITING_FOR_DOMAIN_APPROVAL`을 **`WAITING_FOR_WORD_APPROVAL`과 별도로** 추가했습니다(하나로 일반화하는 안도 검토했지만, 기존 단어 쪽 코드/데이터/UI 라벨을 안 건드리는 쪽을 택함 — 사용자 결정 2026-09-21). 새 컬럼 `depends_on_domain_request_id`(단일 nullable FK, `domain_requests(id)` 참조) — 용어는 도메인을 최대 하나만 가지므로 단어처럼 다대다 테이블이 필요 없습니다.
- `registration.submit()`에 `depends_on_domain_request_id` 파라미터 추가. 단어 의존성과 도메인 의존성이 **동시에** 있으면(용어 하나가 신규 단어와 신규 도메인을 같은 흐름에서 둘 다 필요로 하는 드문 경우) `WAITING_FOR_WORD_APPROVAL`이 우선합니다 — 어느 쪽이 이겨도 정확성엔 영향 없음: `word_registration.approve()`와 `domain_registration.approve()`의 승격 쿼리가 **서로의 의존성 테이블도 같이** 확인한 뒤에만 `PENDING_REVIEW`로 풀어주기 때문입니다.
- `domain_registration.approve()`가 이제 `word_registration.approve()`와 대칭으로 대기 중인 용어를 승격시키고, 반환값에 `promoted_terms`가 추가됐습니다.
- UI(`STATUS_LABELS`/`REGISTRATION_STATUS_LABEL`/상태 필터 드롭다운)에 "도메인 승인 대기" 라벨 추가.

**`domain_suggestion.py`(신규) — `word_suggestion.py`와 동형 구조**: 용어 자신의 정의를 읽어 새 도메인 스펙(코드/도메인그룹/데이터유형/길이/표현형식/허용값)을 초안합니다. 다른 용어들의 도메인 사용 분포를 보는 `search.domain_usage()`(1단계 추천)와는 **완전히 다른 계산**이라, 사용자가 1단계 추천을 전부 거절한 뒤에 실행돼도 같은 결과를 반복 제시할 수가 없습니다. `existing_domain_match`를 `ambiguous`/`code`보다 먼저 선언하는 강제 중간 필드 트릭(word_suggestion.py와 동일)으로 "재사용 가능한 기존 도메인이 있다"와 "신규 스펙을 만든다"를 한 응답에서 동시에 주장 못 하게 막습니다 — 도메인엔 임베딩이 없어서 이 안전 재확인은 유사도 검색이 아니라 활성 도메인 전체(~126건, 작아서 그대로 전송 가능)를 후보로 씀. `rationale` 필드는 제안한 각 값(특히 `data_type`/`data_length`/`valid_values`)이 정의문 속 어느 표현에 근거했는지 한 문장으로 대게 강제 — 근거를 못 대는 값은 애초에 제안하지 말고 되묻도록 프롬프트에 명시(실측: "신용카드, 계좌이체, 간편결제, 포인트 중 하나로 결제 방법을 구분하는 코드"라는 정의로 `valid_values`를 정확히 4개 값으로, `rationale`도 정의를 인용해 채움 — `RUN_LLM_TESTS=1`로 확인). `is_personal_info`는 이 모듈이 절대 추측하지 않음 — 대화 흐름이 스펙 확정 후 별도로 명시 질문하도록 남겨둠(챗봇 연결 시 `awaiting_domain_pii_choice`로 구현).

**챗봇 배선**: `build_chatflow.py`의 `awaiting_domain_choice` 규칙에 "이 중엔 없어요" 같은 문구 → `request_new_domain` 분기 추가, 신규 스테이지마다 CLASSIFY 규칙(`STAGE_RULES`)·RENDER 안내(`domain_spec_hint`/`existing_domain_matched_hint`, word_hint와 동일한 "코드가 문장을 결정, LLM은 다듬기만" 패턴)·퀵리플라이 버튼(`options`)을 추가했고, `domain_spec_unavailable`/`domain_request_blocked`는 기존 `word_request_blocked`처럼 `CLASSIFY_TERMINAL_STAGES`에 편입. `app.js`에 `renderDomainSuggestionCard`/`renderDomainRequestBlockedCard` 추가.

**배포 스크립트 버그 하나 발견**: `dify_admin.py`의 `execute()`가 쓰는 `subprocess.run(...,timeout=150)`이 이 환경에서는 마진이 없었습니다 — `uv run --no-sync --project /app/api python -c "print(1)"`처럼 아무 일도 안 하는 호출조차 60~90초가 걸려서(측정치), 실제 `create_app()`+DSL import 작업을 더하면 150초를 실측으로 초과함 — `timeout=400`으로 올림.

**실사용 중 발견한 진짜 버그 — 수정 요청이 기존 도메인으로 조용히 새치기당함 (2026-09-21)**: 실사용자가 "이 중엔 없어요, 새로 만들래요"로 신규 도메인("기관등록코드") 초안을 받은 뒤 "길이를 12로 해줘"라고 수정을 요청했더니, PII 질문도 건너뛰고 곧장 약어 확정 단계로 넘어가버림 — 실제로는 `existing_domain_match` 안전망이 이 짧은 수정 문구만 보고 **전혀 무관한 기존 도메인**("운전면허번호C12" — 길이가 우연히 12로 같다는 이유만으로)에 매칭시켜, 사용자의 초안과 수정 요청을 통째로 무시하고 그 기존 도메인으로 바로 진행해버린 것이었습니다(실제 대화 상태 DB에서 확인). 원인: `suggest_domain()`을 수정 라운드에서 다시 호출할 때도 매번 전체 활성 도메인(~126건)을 대상으로 안전망 검사를 반복해서 — 전체 정의문 대비 신뢰도가 훨씬 낮은 짧은 수정 문구 하나로 이런 오탐이 나온 것. 해결: `suggest_domain()`에 `allow_existing_match: bool = True` 파라미터 추가 — `confirm_domain_spec`의 수정 루프(`conversation.py`)에서만 `False`로 호출해 `known_domains` 자체를 프롬프트에서 빼고, `fixed_name`(word_suggestion.py)과 동일한 결정론적 강제 초기화로 `existing_domain_match`를 항상 비움. 최초 도메인 선택 거부 시점(`request_new_domain`)과 모호함 재질문 답변 시점은 여전히 안전망이 켜져 있음 — "이미 드래프트를 확정하려는 단계"에서만 꺼짐. 회귀 테스트(`test_real_suggest_domain_correction_never_matches_existing_domain`, `RUN_LLM_TESTS=1`)로 동일 시나리오(같은 길이의 미끼 도메인) 재현·확인.

**바로 이어서 발견한 두 번째 버그 — 수정 요청이 안 건드린 필드까지 같이 바뀜**: 위 수정 직후 실사용자가 바로 재현: 길이만 바꿔달라고 했는데 `code`("한강수질C20"→"수질등급_VARCHAR")와 `domain_group`("수질"→"환경")까지 같이 바뀜. 원인은 더 근본적 — `clarification_history`는 "질문/답변" 텍스트 쌍일 뿐, 이전 드래프트의 실제 필드 값을 모델에게 다시 안 넘겨주고 있었음(모델이 대화 맥락만으로 자기 이전 응답을 "기억"해서 그대로 베끼길 기대한 것 자체가 무리). 처음엔 프롬프트로만 "current_draft를 넘기고 언급 안 된 필드는 그대로 두라"고 시도했지만(SYSTEM 프롬프트에 반영) 실측 결과 여전히 `code`가 바뀜 — 이 프로젝트에서 이미 여러 번 확인된 교훈("작은 모델에게 부탁하지 말고, 코드가 결정하게 하라")이 여기서도 그대로 재현됨. 최종 해결: `DomainSuggestion`에 `changed_fields: list[str]` 필드 추가 — 모델은 "실제로 바뀌어야 하는 필드 이름만" 나열하고, `suggest_domain()`이 `changed_fields`에 없는 모든 필드를 `current_draft`의 원래 값으로 **결정론적으로 강제 복원**함(모델이 값을 그대로 베꼈는지 신뢰하지 않음 — `existing_domain_match`와 같은 방어 철학). 회귀 테스트(`test_real_suggest_domain_correction_only_changes_requested_field`, `RUN_LLM_TESTS=1`)가 실제 스크린샷 시나리오(한강수질C20/수질그룹, 길이만 10으로 변경 요청)를 그대로 재현해서 `code`/`domain_group`/`data_type`/`description`이 전부 원래 값 그대로 유지되고 `data_length`만 바뀌는지 확인. 이후 길이 외 다른 필드(허용값 리스트 추가, 도메인그룹 텍스트 변경)도 각 3회씩 실측해 일반화됨을 확인(`test_real_suggest_domain_correction_adds_valid_value`/`test_real_suggest_domain_correction_renames_domain_group`).

## 용어 신청 간편 입력에 챗봇 수준의 즉시 반응 추가 (2026-09-21)

**동기**: 사용자 요구 — "챗봇에서 반응해주듯이" 간편 입력 폼도 제출 전에 이름 중복 여부를 바로 알려주고, 정의·도메인·영문약어까지 "일일이 묻지 않아도 진행 가능한 영역"은 자동으로 추천해달라는 것. 새 판단 로직은 하나도 만들지 않음 — 챗봇이 이미 쓰는 모듈(`search()`/`validate_name()`/`definition_suggestion.suggest_definition()`/`search.domain_usage()`/`abbreviation.suggest_abbreviation()`)을 그대로 재사용하는 3개 읽기전용 GET 라우트(`admin_api.py`)와 프론트 이벤트 바인딩만 추가.

- **`GET /admin/term-requests/check-name`**: `validate_name()`(형식) → `registration.find_pending()`(대기 중 중복) → `search()`(EXACT_MATCH/SYNONYM_MATCH, 임베딩만 - LLM 없음)를 이 순서로 검사한 뒤 **마지막으로 표준단어 완전분해 검사(`quick_registration.find_word_gaps()`, 2026-09-22 추가 — 아래 "check-name과 제출의 판정 불일치" 참고)**. `registration.prepare()`를 여기서 재사용하지 않은 이유: LLM 기반 SAME_MEANING 비교까지 돌리면 blur 한 번에 수 초가 걸리고 `registration_preparations`에 부작용 있는 행까지 남김 — 그 더 깊은 의미 판단은 여전히 최종 제출 시점의 몫(기존과 동일, 퇴보 아님). `tr-term-name`의 `blur` 이벤트에서 호출 → 통과 시 초록 테두리, 실패 시 빨강 테두리 + 사유 문구(`app.js`의 `setFieldState()`).
- **`GET /admin/term-requests/suggest-definition`**: 이름이 "사용 가능" 판정을 받은 직후 자동 호출 - 버튼 없음. 구체적 정의가 나오면 클릭해서 적용하는 카드(`.field-suggestion-chip`)로, 모호하면(질문+후보) 클릭형 옵션 버튼으로 보여줌 - 둘 다 적용 전까지는 `tr-definition`을 건드리지 않음(챗봇 카드와 같은 "제안 vs 자동적용" 원칙).
- **`GET /admin/term-requests/suggest-followups`**: 이름 통과 + 정의 입력(제안 클릭 또는 직접 작성 후 blur) 시점에 도메인 추천(`domain_usage()`)과 영문약어 추천(`suggest_abbreviation()`)을 한 번에 묶어 호출. **도메인/영문약어 필드가 비어있을 때만** 값을 채워넣음(사용자가 이미 직접 입력한 값은 절대 덮어쓰지 않음) - 추천 근거는 필드 아래 회색 문구로만 표시(`.field-suggestion-note`), "직접 입력해 바꿀 수 있습니다"라고 항상 안내. 도메인 추천이 채워지면 기존 `populateTermDomainDerivedFields()`(허용값/표현형식/저장형식 참고 표시)도 자동으로 같이 실행됨.

프론트는 매 비동기 호출마다 fetch-token(예: `termNameCheckToken`)으로 낡은 응답이 최신 입력을 덮어쓰지 않게 막음 - `populateTermDomainDerivedFields()`의 기존 `termDomainDerivedFetchToken` 패턴과 동일. 브라우저로 직접 확인(2026-09-21): 기존 용어명 입력 → 빨강 테두리+"이미 등록된 표준용어입니다" 즉시 표시, 신규 이름 → 초록 테두리 → 정의 추천 카드 등장 → 클릭 시 도메인("수N7", 비교군 43% 사용)·영문약어("DAILY_MST_INTK", 조합 근거 포함) 자동 채움까지 실제 동작 확인.

**배포 직후 실사용자가 바로 잡아낸 버그 둘**:
1. **모호함 질문의 안내문구·버튼이 겹침** — `.field-suggestion-note`/`.field-suggestion-options`가 둘 다 음수 `margin-top`을 쓰고 있어서(다른 곳에서 입력창 바로 아래에 붙일 땐 의도한 효과였지만, 여기서는 두 요소가 연달아 있어 음수가 누적됨) 질문 문장과 선택 버튼이 거의 겹쳐 보였음. 전용 클래스 `.field-suggestion-question`을 새로 만들어 양의 여백으로 교체.
2. **후보 버튼을 클릭하면 그 라벨이 그대로 정의로 들어감** — "변경 이후에 할당된 주소 코드"라는 후보 라벨은 "이 의미가 맞다"는 답일 뿐 완성된 정의 문장이 아닌데, 그대로 `tr-definition`에 꽂아 넣고 있었음. 챗봇의 `set_definition`이 옵션 선택을 절대 정의 자체로 취급하지 않고 `clarification_history`에 답을 추가해 `suggest_definition()`을 다시 부르는 것과 똑같이 고침 — `suggest-definition` 라우트가 이제 `clarification_history`(JSON 쿼리 파라미터) 를 받아 `suggest_definition()`에 그대로 전달하고, 프론트는 후보 클릭 시 이 라운드트립을 거쳐 받은 진짜 정의 문장을 적용함(이미 한 번 선택이라는 의사표시를 했으므로 추가 클릭 요구 없이 바로 반영). fetch를 모킹해 모호함→후보 클릭→완성된 정의 문장 반영까지 결정론적으로 재현해 확인(LLM이 항상 모호하게 답하진 않아 실제 API로는 재현이 들쭉날쭉했음).

**실 배포 후 curl 대신 진짜 `/v1/chat-messages` 스트리밍으로 처음부터 끝까지 3회 검증**(단어 갭 있는 용어 → 도메인 전체 거절 → 신규 스펙 초안 → PII 질문 → 약어 → 최종 등록 → `manage.py approve-domain` → 용어 자동 `PENDING_REVIEW` 승격까지 실제 DB에서 확인) 하는 과정에서 **이번 작업과 무관한 기존 버그**를 하나 발견: `set_word_abbreviation`이 `word_registration.submit()`의 `PENDING_REQUEST_ALREADY_EXISTS`(같은 이름의 단어가 다른 대화에서 이미 대기 중일 때)를 처리하지 않고 `term_pending_words`에 아무것도 추가하지 않은 채 그냥 용어 흐름을 재개시켜버립니다 — 그 결과 용어가 실제로는 미승인 단어에 의존하면서도 의존성 추적 없이 곧장 `PENDING_REVIEW`로 제출됩니다. pytest는 매 테스트마다 `word_registration_requests`를 비우는 `terms_test` DB를 써서 이 경로를 한 번도 못 건드렸습니다 — 이번 세션에서 같은 신규 단어("간편")로 반복 테스트하다가 실제 개발 DB에서 처음 걸림. **2026-09-22 수정됨**: `_resume_or_finish_word_flow(s, result_stage)`에 `succeeded` 매개변수를 추가 — `resume_term`이 있어도 `succeeded=False`면 더 이상 복귀하지 않고 `result_stage`(`word_registration_failed`)로 바로 종료하며 `resume_term`/`term_pending_words`를 버림(용어 등록 도중이 아닌 standalone 진입에서 실패했을 때와 동일한 취급 — `word_request_blocked`가 `prepare()` 실패 시 이미 하던 것과도 같은 원칙). 호출부(`set_word_abbreviation`)는 `submit()` 결과에 `request_id`가 있을 때만 `succeeded=True`를 넘김. 프론트 `renderWordResultCard`도 `word_registration.code`만 있고 `request_id`가 없는 경우(이 실패)에 빈 카드 대신 실패 사유 코드를 보여주도록 보강(전에는 카드가 아예 안 뜨고 LLM 문장에만 의존했음). 회귀 테스트(`test_word_flow_resume_does_not_silently_swallow_a_failed_submit`) — `insert_pending_word()`로 다른 사용자가 같은 이름의 단어를 이미 신청해 둔 상태를 실제로 만들고, 임베디드 단어 서브플로우가 그 이름과 충돌해 실패할 때 대화가 `word_registration_failed`로 끝나고 `resume_term`/`term_pending_words`가 비는지 확인(제안 LLM만 스텁, `word_registration.prepare()`/`submit()`은 실제 Postgres로 실행). 전체 테스트 106 passed / 11 skipped. 이 수정은 `conversation.py`의 순수 상태머신 로직이라 Dify 프롬프트(`build_chatflow.py`/`dify-chatflow.yaml`) 변경이 없고, 재배포 3단계 없이 MCP 서버 재시작만으로 반영됨.

## check-name과 제출의 판정 불일치: "가드레일" (2026-09-22)

**증상(사용자 실사용)**: 용어명 "가드레일"을 입력하면 초록("사용 가능한 이름입니다")이 되고 정의·도메인·영문약어 추천까지 채워지는데, 신청 버튼을 누르면 "다음 부분이 아직 표준단어로 등록되지 않았습니다: 가드레일"로 거절됨.

**원인**: 입력 중 이름 확인(`GET /admin/term-requests/check-name`)과 제출(`quick_registration.prepare_term`)이 **서로 다른 검사 집합**을 돌고 있었음. 제출은 표준단어 사전 완전분해(`segment_words`)를 맨 먼저 하는데, check-name은 형식→대기중복→정확/동의어 일치만 하고 이 검사가 없어서 사전에 없는 단어("가드"/"레일"은 실제로 사전에 없음, 이름 전체가 gap)가 섞인 이름도 "사용 가능"이라고 답했음. 2026-09-21의 즉시 반응 작업 때 "챗봇이 정의를 묻기 *전에* 하는 검사"를 옮기면서 `confirm_term`의 단어 갭 검사(같은 위치에 있음)를 빠뜨린 것. 더 나쁜 점은 그 초록 판정이 후속 추천(LLM)의 **게이트**라서, 등록 못 할 이름에 대해 정의/도메인/약어 추천이 다 돌았다는 것(스크린샷의 `가드레일` → 도메인 "요금N15", 약어 "GDRL"은 LLM이 지어낸 값이었음). "주간식단"처럼 사전에 없는 단어가 섞인 이름은 전부 같은 증상이었음.

**수정**: `quick_registration.find_word_gaps(term_name)`(사전 완전분해 실패 시 gap 목록, 통과/사전 비어 있음이면 `None`)를 만들어 **제출(`prepare_term`)과 check-name이 같은 함수**를 쓰게 함. check-name은 새 상태 `word_gap`(+`gaps`, `message`)을 돌려주고 프론트는 이미 "available이 아니면 빨강+사유, 후속 추천 안 함"으로 처리하므로 프론트 판정 로직 변경은 없음(제출 시 문구만 서버의 `word_gap_message()`를 그대로 쓰도록 통일). LLM/임베딩 없이 DB 1회+문자열 처리뿐이라 입력 중 호출해도 안전. 회귀 테스트 3개(`test_check_term_name_word_gap_is_not_reported_as_available`, `..._fully_decomposable_name_stays_available`, `test_check_name_verdict_agrees_with_submit_word_gap_check` — 마지막은 두 경로의 판정이 같은지 직접 대조).

**일반화 — 새 검사를 제출 경로에 추가할 때**: check-name(입력 중 미리보기)은 제출 검사의 **부분집합이 아니라 "LLM/부작용 없는 검사 전부"** 여야 함. 제출 쪽에 저렴한 결정론적 검사를 추가하면 check-name에도 같은 함수로 넣을 것(지금 남은 차이는 `registration.prepare()`의 LLM 기반 SAME_MEANING 비교뿐이고 이건 의도적 — 위 즉시 반응 절 참고). 반대로 check-name이 "초록"이라고 한 이름이 제출에서 다른 이유로 거절되는 경우가 생기면 이 절과 같은 종류의 버그임.

**범위 밖(의도적 결정, 2026-09-22 — 작업 후보 아님)**: `word_gap`으로 막힌 사용자를 "단어 신청" 탭으로 바로 안내하는 링크/버튼은 만들지 않기로 함(문구 안내로 충분하다고 판단). 갭이 여러 단어로 쪼개질 수 있는 경우("소리동굴" → "소리"+"동굴")의 선택 UI도 챗봇의 `awaiting_word_split_choice`에만 있고 간편 입력엔 없음 — 둘 다 다음에 다룰 후보가 아니라 하지 않기로 확정된 항목.

## 용어 신청: AI 추천 ON/OFF 토글 + 제출 시 칸별 빨간 테두리 + 초기화 아이콘 이동 (2026-09-21)

**동기(사용자 요구)**: 중복 기능인 AI 대화 카드를 없애고, 위 "즉시 반응"(이름 확인/정의·도메인·약어 추천)을 쓰고 싶지 않은 사용자를 위해 끌 수 있게 하되, 끈 사용자에게는 대신 **신청 버튼을 눌렀을 때 안 되는 칸을 빨간 테두리로** 알려줄 것. 변경은 전부 프론트엔드(`term-standardization-ui`)이고 백엔드/Dify 배포는 없음.

- **토글 (`termAiAssist`, `setTermAiAssist()`)**: 용어 신청 헤더 오른쪽 위의 스위치. 기본 ON, **저장하지 않음**(새로고침하면 다시 ON — "기본은 ON으로 시작"). OFF면 `checkTermName()`과 `maybeSuggestFollowups()`가 맨 앞에서 return해서 `check-name`/`suggest-definition`/`suggest-followups` 세 라우트를 **아예 호출하지 않음**(정의 추천은 `termNameStatus==="available"`일 때만 도는데 그게 OFF에선 `""`로 유지되므로 함께 막힘). 끄는 순간 `clearTermAiSuggestions()`가 화면의 추천/판정을 걷고 진행 중이던 fetch 토큰을 전부 무효화해서 뒤늦게 도착한 응답이 칸을 채우지 못하게 함 — **입력한 값은 지우지 않음**. 이름을 적어둔 채 다시 켜면 `checkTermName()`을 바로 실행. 도메인을 고르면 허용값/표현형식/저장형식을 보여주는 `populateTermDomainDerivedFields()`는 "AI 추천"이 아니라 도메인 조회이므로 OFF에서도 계속 동작.
- **제출 검증은 ON/OFF와 무관하게 항상 동작**: 폼에 `novalidate`를 줘서 브라우저 기본 말풍선 대신 `validateTermForm()`이 모든 문제 칸을 한꺼번에 빨갛게 표시(용어명 2~20자, 정의 5~4000자, 도메인 필수 — `schemas.RegistrationInput`의 제한과 동일하게 맞춘 값이므로 스키마를 바꾸면 여기도 같이 바꿀 것). 브라우저 검증을 통과하면 서버로 가고, 서버의 거부 코드를 `TERM_ERROR_FIELDS`로 칸에 매핑(`GUIDELINE_VIOLATION`/`EXACT_MATCH`/`WORD_GAP_REQUIRES_REGISTRATION`/`PENDING_REQUEST_ALREADY_EXISTS` → 용어명, `SAME_MEANING` → 용어명+정의, `SYNONYM_CONFLICT` → 동의어, `ABBREVIATION_ALREADY_USED` → 영문약어; `INVALID_FIELDS`는 pydantic `detail[].loc[0]`이 칸 이름). **미등록 도메인은 서버가 거부하지 않고** `UNREGISTERED_DOMAIN_REQUIRES_REVIEW` 경고만 붙여 접수하므로(`registration.prepare()`) 도메인 칸은 "비어 있음"만 실패로 봅니다 — 이걸 실패로 바꾸려면 서버 정책부터 바꿔야 함. 칸 값을 고치기 시작하면 그 칸의 빨간 표시는 사라짐. `CATALOG_CHANGED_*` 같은 칸과 무관한 코드는 하단 에러 문구만 표시.
- **오류 표시 후 `focus()`를 쓰지 않는 이유**: 이름 칸에 focus→blur가 일어나면 ON 모드의 `checkTermName()`이 다시 돌아 방금 표시한 빨간 표시(예: `SAME_MEANING` — `check-name`은 이 판정을 못 하므로 "사용 가능"이 됨)를 초록으로 덮어쓸 수 있음. 그래서 `scrollIntoView`만 함. 같은 이유로 이 로직을 고칠 때 "이름 칸에 포커스를 주는" 동작을 추가하지 마세요.
- **초기화 버튼**: 채팅창의 "새 대화 시작"(`#chat-reset`)과 **같은 회전 화살표 아이콘/`chat-icon-btn` 스타일**을 용어 신청 헤더 오른쪽 위로 옮김(하단의 텍스트 "초기화" 버튼과 `.form-actions` 래퍼는 삭제). 채팅창 버튼 자체를 공유하는 것은 아님(그건 대화 상태 초기화용) — 모양만 같은 별도 버튼 `#term-request-reset`. `resetTermRequestForm()`은 제출 성공 후 초기화와 **공용**이며 입력값·추천·오류 표시를 전부 비우되 **ON/OFF 선택은 유지**함.
- **검증(2026-09-21, 로그인한 실제 화면)**: OFF에서 이름 blur 시 서버 요청 0건, 정의/도메인 비운 채 신청 → 두 칸만 빨강, 기존 이름("공사구분명")으로 신청 → 서버 `EXACT_MATCH`로 용어명 칸만 빨강+사유, 초기화 후에도 OFF 유지, 이름 입력 후 ON 전환 시 즉시 확인 시작, ON에서 추천 응답이 오는 도중 초기화해도 칸이 다시 채워지지 않음. **성공 경로(실제 접수)는 이번 변경 후 다시 확인하지 않았음** — 실제 신청이 DB에 남기 때문.
- **동의어 100자 초과 → 500 (2026-09-22 해결)**: `create_term_request`(그리고 같은 패턴의 단어/도메인 신청 라우트)가 `INVALID_FIELDS` 응답에 `exc.errors()`를 그대로 실었는데, pydantic이 `field_validator`의 `ValueError`를 `ctx`에 **객체로** 담아서 동의어에 100자 초과 항목이 있으면 JSON 직렬화가 실패(`Object of type ValueError is not JSON serializable`)해 400이어야 할 응답이 500이 됐음. `admin_api._validation_detail(exc)`(`include_context=False, include_url=False, include_input=False`)를 세 라우트가 공용으로 쓰도록 고침 — `input`도 뺀 이유는 사용자가 보낸 원문(정의는 최대 4000자)을 응답에 되돌려 싣지 않기 위해서고, 클라이언트가 쓰는 건 `loc`뿐임(`detail[].msg`는 pydantic 영문 메시지라 화면에 그대로 쓰지 말 것). 프론트 `validateTermForm()`에도 동의어 검사(각 100자, 최대 30개)를 추가해 서버까지 가기 전에 동의어 칸을 빨갛게 표시. 회귀 테스트 2개(`test_term_request_overlong_synonym_returns_400_not_500`, `test_invalid_fields_detail_is_json_safe_and_does_not_echo_input`). **새 `field_validator`를 `schemas.py`에 추가하거나 새 `INVALID_FIELDS` 라우트를 만들 때는 `exc.errors()`를 직접 싣지 말고 이 헬퍼를 쓸 것.**

## 단어 신청 / 도메인 신청 간편 입력에 AI 추천 붙이기 (2026-09-22)

**동기(사용자 요구)**: 용어 신청처럼 단어 신청·도메인 신청 탭에도 AI 추천을 붙일 것. 시작하기 전에 챗봇 서브플로우와 신청 폼 필드를 대조했더니, 둘 다 "그대로 재사용"이 안 되는 지점이 있었음(아래 각 절 참고) — 하나는 **입력 모델 자체가 다르고**(단어), 하나는 **모듈의 원래 목적이 다름**(도메인). 두 경우 모두 사용자에게 방향을 먼저 확인받고 진행함(`AskUserQuestion`).

### 단어 신청: "이름 먼저" 폼과 "의미 먼저" 챗봇의 충돌

간편 입력 폼은 원래 **단어명을 사용자가 직접 입력**하는 구조였음(`word_registration.prepare()`도 정확 문자열 일치만 확인). 반면 챗봇의 `word_suggestion.suggest_word()`는 위 "표준단어 계층" 절의 원칙("단어 등록은 이름이 아니라 의미가 입력") 그대로, **의미 설명**을 받아 이름을 AI가 짓는 구조 — 폼의 단어명을 그대로 `suggest_word()`에 넣는 건 이 원칙에 어긋나므로 하지 않음.

사용자가 선택한 방향("의미 설명 필드 추가")대로, `wr-usage-description`(정의 위 새 필드, AI 추천 OFF면 숨김)을 새로 만들어 blur 시 `GET /admin/word-requests/suggest`(`usage_description`+`clarification_history`)를 호출 → `word_suggestion.suggest_word()`를 그대로 재사용. 용어 신청과 달리 트리거 시점이 "의미 설명 칸을 벗어날 때" **하나뿐**이라 라우트도 하나로 충분함(용어처럼 3개로 쪼갤 필요 없음 — `existing_word_match`/`ambiguous`/새 이름+정의+영문약어+형식단어 초안이 한 응답에 다 옴). `fixed_name`은 항상 빈 문자열(용어 등록 도중 자동 분기된 임베디드 진입 전용, 간편 입력은 독립 진입이라 고정할 표기가 없음 — 회귀 테스트로 확인).

- `existing_word_match`가 있으면 이름/정의/약어를 **채우지 않고** 빨간 경고 카드만 보여줌(재사용은 사용자 결정).
- `ambiguous`면 질문+후보 버튼(용어 신청의 정의 모호함 처리와 동일 패턴) — 클릭하면 `clarification_history`에 답을 쌓아 재호출.
- 성공하면 이름/정의/영문약어/형식단어를 **하나의 초안 묶음**으로 취급해 단어명이 비어있을 때만 채움(용어 신청의 "빈 칸에만 채운다" 원칙과 동일).
- **`도메인분류`(`wr-domain-classification`) 필드는 챗봇 어디에도 대응이 없음** — `conversation.py`가 단어를 제출할 때 이 필드를 채우지 않아(항상 `""`), 챗봇으로 등록한 단어는 이 값이 항상 빈 문자열임. AI 추천 대상에서 제외하고 항상 수동 입력으로 남김(의도적).

### 도메인 신청: `domain_suggestion`은 "용어→도메인" 모듈이지 "도메인 자기설명" 모듈이 아님

챗봇의 신규 도메인 서브플로우(`domain_suggestion.suggest_domain(term_name, definition, ...)`)는 **등록 중인 용어의 이름+정의**를 보고 그 용어에 필요한 도메인 스펙을 짓는 모듈(위 "신규 도메인 의존성 처리" 절 참고) — 도메인 신청 폼처럼 "이 도메인 자체를 설명해주세요"를 받는 물건이 아님. 사용자가 선택한 방향("설명 기반 자동추천 + 중복확인")대로, 폼의 **설명**(`dr-description`) 칸 내용을 `definition` 자리에 그대로 넘기고, 사용자가 이미 적어둔 `도메인명(코드)`(없으면 도메인그룹)을 `term_name` 자리에 힌트로 대신 넘김(`GET /admin/domain-requests/suggest` — `term_name`은 실제로는 프롬프트 문맥과 가이드라인 검색 쿼리에만 쓰여서 완전히 대체 가능, `domain_suggestion.py`의 사용처 참고).

- `existing_domain_match`가 있으면(의미상 이미 비슷한 도메인이 있음) 자동 채우기 없이 빨간 경고만 — **도메인 신청은 지금까지 코드 문자열 중복만 확인**했으므로(`domain_registration.prepare()`), 이게 처음 생긴 의미 중복 확인임. 실측: "신용카드, 계좌이체, 간편결제, 포인트 중 하나로 결제 방법을 구분하는 코드"로 실제 정부 표준 도메인 `결제수단코드C10`과의 겹침을 정확히 잡아냄.
- 성공하면 `code`/`domain_group`/`data_type`/`data_length`/`decimal_length`/`display_format`/`valid_values`를 빈 칸에만 채움. **`description`은 채우지 않음** — 사용자가 이미 써서 이 추천을 촉발한 트리거 텍스트 그 자체라, AI가 다시 쓴 문장으로 덮어쓰면 방금 쓴 내용이 사라지는 것처럼 보임(용어 신청의 정의 추천과는 반대 — 거기선 입력이 빈 정의칸을 "채우는" 것이었지만, 여기선 입력 자체가 이미 정의문 역할을 함).
- `물리명`/`최소값`/`최대값`/`출처구분`/`기본값`/`신청사유`/`개인정보여부`/`암호화여부`/`매핑 테이블·컬럼` — 폼에만 있고 **챗봇의 `domain_suggestion`엔 대응이 전혀 없는** 필드들(개인정보여부는 챗봇에서 별도 명시 질문 `set_domain_pii`로 묻지만 LLM 추천이 아니라 단순 Y/N). 폼 필드 20개 중 8개만 AI 추천 대상이고 나머지는 계속 수동 입력 — AI가 추천할 근거 자체가 정의문에 없는 내용이라 의도적으로 남겨둠.

### 공통 구현

용어 신청과 같은 패턴(`.ai-toggle`, `panel-header-actions`, `field-hint`)을 재사용 — 헤더 우측 상단 ON/OFF 스위치(기본 ON, 저장 안 함), fetch 토큰으로 낡은 응답 무효화, `novalidate`+칸별 빨간 테두리(`WORD_FIELDS`/`DOMAIN_FIELDS` — 도메인은 20개 필드 중 실제로 서버가 자주 거부하거나 사용자가 틀리기 쉬운 5개(코드/그룹/유형/길이/소수점)만 칸별 표시, 나머지는 하단 오류 문구만). 새 CSS `.field-suggestion-warning`(danger 톤 — "이미 있으니 재사용하라"는 초록 칩/회색 안내와 다른 무게의 메시지).

**단어 신청의 "AI와 대화하며 등록" 카드도 결국 삭제함(2026-09-22, 최초 판단을 뒤집음)**: 처음엔 "헤더 버튼과 겹치지 않는 별개 흐름"이라며 남겨뒀으나, 실제로는 헤더의 "+ 신규 용어 등록"이 여는 챗봇의 첫 인사말에 이미 "③ 단어를 등록할래요" 옵션이 있어서 **완전히 중복**이었음(사용자 지적) — 용어 신청과 동일하게 카드/버튼 삭제, 헤더의 회전 화살표 초기화 아이콘(`#word-request-reset`, `resetWordRequestForm()` 재사용)으로 대체. 도메인 신청은 원래도 챗봇 카드가 없었음(버튼식 직접 입력 폼) — 그대로.

**배포 직후 실사용자가 잡아낸 것 둘 더**:
1. **AI 추천 결과 문구가 textarea에 바짝 붙어 겹쳐 보임**: `#wr-word-suggestion`/`#dr-domain-suggestion`이 담는 `.field-suggestion-note`/`.field-suggestion-warning`이 음수 top margin(`-6px`, 다른 위치에서 쓰기 위한 값)을 그대로 물려받아 바로 위 textarea 하단에 거의 붙었음. 이 두 컨테이너 안에서만 `margin-top`을 양수로 되돌리는 CSS를 추가(자세한 이유는 style.css 주석 참고).
2. **"도메인분류" 칸에 "선택"이라고만 써 있고 실제 선택지가 없음**: 자유 입력 텍스트칸인데 placeholder가 "선택"이라 드롭다운처럼 보였음. 실제로 정부 표준 사전(`standard_words.domain_classification`)에 이미 쓰이는 값이 545건(수/금액/율/비용/면적 등)이나 있는데 아무것도 안 보여주고 있었던 것 — 새 `GET /admin/word-requests/options`가 그 실제 값 목록(중복 제거)을 돌려주고, `<datalist>`로 연결해 자유 입력은 유지하면서 실제 값을 골라 쓸 수 있게 함(도메인 신청의 `dr-domain-group-options`와 같은 패턴). placeholder도 "선택 입력 (예: 금액, 수, 율)"로 명확히 함.

**세 번째로 잡아낸 것 — 필드 20개짜리 도메인 신청 폼이 흰 카드 밖으로 잘려 보임(2026-09-22)**: 원인은 "표준 데이터 조회"의 "조회"(표) 탭 전용으로 설계된 고정 레이아웃 CSS(`#view-catalog .panel { flex:1; min-height:0 }` — 위 "SaaS형 고정 레이아웃" 관례)가 셀렉터를 `#view-catalog .panel`로 걸어놔서 **신청 탭 3개에도 전부** 적용되고 있었던 것. 용어/단어 신청 폼은 짧아서 그 안에 우연히 다 들어가 안 보였지만, 필드 20개인 도메인 신청 폼은 패널에 할당된 높이를 넘겼고, `<form>` 자체엔 내부 스크롤이 없어서 넘친 부분이 흰 카드 배경 밖(회색 페이지 배경 위)으로 그냥 삐져나와 보였음. **수정**: 그 고정 레이아웃 규칙의 셀렉터를 `#view-catalog .panel`에서 `#catalog-tab-browse .panel`로 좁혀서 표 탭에만 적용되게 함 — 신청 폼 탭들은 이제 내용물 크기만큼 자연스럽게 늘어나고, 넘치는 부분은 `.catalog-tab-panel`(각 탭의 바깥 래퍼)의 `overflow-y:auto`가 맡음 — 사이드바/상단바/탭 줄은 여전히 고정, 그 아래만 스크롤되는 원래 의도는 그대로 유지됨. 실제 화면으로 도메인 신청 폼 끝까지 스크롤해 "신청" 버튼까지 흰 카드 안에 들어오는지 확인.

**같은 턴에 처리한 나머지 요청**: 도메인 신청 헤더에도 용어/단어와 같은 초기화 아이콘(`#domain-request-reset`, 기존에 만들어져 있던 `resetDomainRequestForm()`을 그제야 버튼에 연결 — 함수는 있었는데 누르는 곳이 없었음).

**검증**: 백엔드 라우트 2개(`/admin/word-requests/suggest`, `/admin/domain-requests/suggest`)에 회귀 테스트 8개(인증/필수 파라미터/모호한 JSON/파라미터 전달·`fixed_name` 고정 확인). 실제 로그인 화면·실제 LLM으로 확인: 단어 — "방문객이 시설을 이용하기 전에 신원과 방문 목적을 등록하는 절차"를 설명하면 "방문등록"/정의/영문약어 "VREG"가 자동 채워짐, 기존 단어("도로")의 정의를 그대로 설명하면 재사용 경고만 뜨고 이름은 안 채워짐. 도메인 — 실제 정부 표준과 겹치는 설명은 `결제수단코드C10` 재사용 경고, 겹치지 않는 설명("반려동물 등록번호... 15자리 고정 길이 코드")은 `등록번호C15`/CHAR/15로 자동 채움(설명 칸 자체는 그대로 유지). AI OFF에서 빈 폼 제출 시 서버 요청 0건 확인. 전체 테스트 114 passed / 11 skipped.

## 세 신청 폼 모두 "개념 설명 먼저" 흐름으로 통일 + 용어 신청도 개념 검색 추가 (2026-09-22)

**동기(사용자 요구)**: 단어/도메인처럼, 용어 신청도 "사용하려는 개념"을 맨 위에서 먼저 받고 그걸로 AI 도움을 받는 흐름으로 통일할 것. 세 폼 다 첫 질문 문구도 "사용하고자 하는 OOO는 어떤 개념인가요?"로 맞춤.

- **단어/도메인은 그대로 위치·문구만 정리**: 단어는 이미 맨 위였고(`wr-usage-description`) 라벨만 "사용하고자 하는 단어는 어떤 개념인가요?"로 통일. 도메인은 `dr-description`을 폼 중간에서 맨 위로 옮기고 같은 방식으로 라벨을 바꿨다(제출 payload의 `description` 필드 자체는 그대로 — 위치만 이동). AI 추천 트리거(blur)도 필드 id 불변이라 그대로 동작.
- **용어는 단순 이동이 아니라 설계 확인이 필요했음** — 사용자에게 먼저 확인받은 지점: 단어 신청의 "의미 → AI가 이름까지 짓는다" 구조를 용어에 그대로 옮길 수 없음. **표준용어는 표준단어의 조합**이어야 하는 이 시스템의 핵심 거버넌스 때문에, 용어명은 AI가 자유롭게 지으면 안 되고 계속 사용자가 직접 입력해야 함(위 "표준단어 계층" 절). 두 가지 방향(설명은 참고 자료로만 / 설명만으로 AI가 이름까지 초안) 중 **"설명은 참고 자료로만" 쪽으로 확정** — 이름은 계속 직접 입력.
- **구현은 새 LLM 모듈 없이 기존 함수 재사용으로 완결**:
  1. 맨 위 새 필드 `tr-concept-description`(AI 추천 ON일 때만 보임, `#tr-ai-suggest-block`) blur 시 새 라우트 `GET /admin/term-requests/check-concept`를 호출 — `search()`를 그대로 재사용하되, `term` 인자에 **자유 서술문을 그대로** 넘긴다(`SearchInput.term`은 최소 1자 제약뿐이고 형식 검증이 없어 이름이 아닌 문장도 그대로 통과 - `validate_name()`은 아예 거치지 않음, check-name과 다른 지점). exact/synonym/lexical은 문장을 이름처럼 취급하니 사실상 항상 비고, `semantic_matches`(임베딩 유사도, 이미 `SEMANTIC_THRESHOLD`로 필터링됨)만 실제 신호. 겹치는 기존 용어가 있으면 빨간 경고로 이름·정의·유사도%를 나열(제출을 막지 않음, 참고용 - 용어명 칸은 여전히 비어 있음). 실측: "하루 동안 섭취한 열량의 총합을 나타내는 값입니다" → `일일섭취칼로리`(88%) 등 실제 정부 표준 4건을 정확히 잡아냄.
  2. `checkTermName()`이 이름을 "사용 가능"으로 판정하면, `tr-concept-description`에 값이 있을 때 그걸 **`suggest_definition()`의 `clarification_history` 첫 항목**(`{question: "이 용어를 어떤 개념으로 사용하려고 하나요?", answer: <설명>}`)으로 얹어서 정의 추천을 부른다 - 백엔드 라우트/스키마 변경이 전혀 없음(그 파라미터는 이미 있었음). 실제 네트워크 요청으로 이 페이로드가 정확히 실리는 것을 확인.
  3. **자동 적용 신호를 `history.length`에서 명시적 `confirmed` 플래그로 분리**해야 했음 - 원래 `suggestDefinitionForTerm()`은 "`history`가 있으면(=모호함 질문에 답한 뒤) 칩을 안 거치고 바로 반영"했는데, 개념 설명을 시드로 얹으면서 `history`가 항상 채워지게 됐다. 그대로 뒀다면 클릭 한 번 없이 정의가 자동 적용돼 "제안 vs 자동적용"(CLAUDE.md 반복 원칙) 을 깨뜨렸을 것 - `confirmed` 매개변수를 추가해 실제로 모호함 옵션을 클릭한 재귀 호출에서만 `true`를 넘기도록 분리. 실제 화면에서 칩이 여전히 클릭해야 적용되는지 확인(자동 적용 안 됨).
  4. `tr-concept-description`은 **제출되는 필드가 아님** - `RegistrationInput`에 없고, 제출 payload에도 안 실림(참고용으로만 브라우저에 남음). `clearTermAiSuggestions()`/`setTermAiAssist()`/`resetTermRequestForm()`도 각각 이 블록의 표시/토큰/값을 같이 정리하도록 확장.
- **검증**: 새 라우트에 회귀 테스트 3개(인증/빈 설명/실제 겹치는 용어 탐지 - `catalog` fixture의 "일일섭취칼로리" 재사용). 실제 화면: 겹치는 개념 설명 → 경고 카드 4건 정확히 표시, 이름 입력 후 정의 추천이 개념 설명을 `clarification_history`로 실어 호출하는 것을 네트워크 요청으로 직접 확인, 클릭 전까지 정의 칸 비어있음(자동 적용 안 됨) 확인, AI OFF 시 개념 블록 숨김/ON 복귀 시 재표시 확인. 전체 테스트 119 passed / 11 skipped.

## 두 개의 독립된 벡터/RAG 시스템 — 절대 섞지 마세요

1. **MCP 자체 pgvector** (`term_service/embeddings.py`, `search.py`, `guideline.py`) — `standard_terms`(용어 유사도/중복 판정), `guideline_chunks`(`standard_guide.md`를 벡터화, 가이드라인 준수 검사·약어 추천·정의 추천의 근거), `standard_words`(2026-09-14 추가 — 의미로 기존 단어 찾기, 위 "표준단어 계층" 절 참고)를 담당. **이게 업무 판단의 기준**입니다.
2. **Dify 자체 지식베이스** (`sync_dify_knowledge.py`가 Weaviate에 업로드) — `show_candidates`/`help` 의도일 때만 참고 자료로 노출되는 보조 지식. **업무 판단에 관여하지 않습니다.**

두 시스템 다 같은 소스 파일(`scenario_catalog.json`, `standard_guide.md`)에서 만들어지지만 완전히 별개의 인덱스이므로, 하나를 고치고 다른 쪽 재동기화를 잊으면 데이터가 어긋납니다. MCP 쪽은 `manage.py import-catalog`/`import-guideline`(start.sh/ps1이 매번 자동 실행), Dify 쪽은 `sync_dify_knowledge.py`(setup_dify.py 3단계, 자동 재실행 안 됨 — 문서 내용을 바꿨으면 수동으로 다시 돌려야 함).

## 반복해서 발견한 엔지니어링 패턴: "작은 모델에게 부탁하지 말고, 코드가 결정하게 하라"

`CLASSIFY_MODEL = gpt-4o-mini`(비용 때문에 의도적으로 저사양 모델 사용, `build_chatflow.py` 상단 참고)로 이 세션 내내 반복된 실패 패턴이 있습니다: **"이 데이터가 있으면 이렇게, 없으면 저렇게 말해라" 같은 조건부 지시를 프롬프트로만 주면 모델이 자꾸 무시하거나 잘못된 분기를 탑니다.** 매번 같은 방식으로 고쳤고, 새 기능을 붙일 때도 이 패턴을 기본으로 쓰세요:

- **가이드라인 검사** (`guideline.py`): "정확히 이 단어와 문자열이 같을 때만 위반"이라고 프롬프트로 아무리 강조해도 모델이 "느낌상 포괄적이다"로 위반 처리했습니다 → `matched_forbidden_word`를 `compliant`보다 먼저 선언한 필드로 만들어 강제로 먼저 답하게 하고, **코드에서 `matched_forbidden_word != term_name`이면 `compliant`를 강제로 덮어씀**(모델이 뭐라 답하든 무시).
- **도메인/비교 표 중복 방지** (`build_chatflow.py`의 `render_context`): "화면에 표로 보여주니 문장에서 반복하지 마라"라고 지시해도 모델이 `business_result.state`에 원본 데이터가 남아있으면 그대로 베껴 썼습니다 → **표/카드로 대체되는 원본 데이터를 아예 `{"note": "..."}`로 마스킹해서 모델 프롬프트에서 보이지 않게 함.** 옵션 라벨(도메인 설명 등 긴 텍스트를 담음)도 `context` JSON에서 분리해 별도 output 필드로 빼서, reply LLM 프롬프트에는 아예 노출되지 않게 했습니다.
- **정의 안내 문구 선택** (`definition_hint`): "제안이 있으면/없으면/질문이면" 세 가지 문구 중 하나를 플래그 보고 고르라고 시켰더니 계속 틀렸습니다(불리언 2개 조합 분기는 모델에게 너무 어려움) → **어떤 문장을 써야 하는지 자체를 파이썬 코드에서 결정**(`definition_hint`/`existing_match_hint` 변수)하고, 모델은 그 문장을 자연스럽게 다듬어 전달하는 역할만 하게 축소.
- **"unknown일 때 예시 목록에 없는 stage" 환각** (2026-09-14 실사례): RENDER 프롬프트의 "next_action이 unknown이면 stage별로 이렇게 안내하라"는 규칙에 `awaiting_term_confirm`이 예시 목록에서 빠져 있었습니다. 분류가 드물게(gpt-4o-mini는 `temperature=0.1`이라 완전히 결정론적이지 않음) 그 단계에서 unknown으로 미끄러지자, 모델이 목록에 있던 **다른 단계(도메인 선택) 예시를 끌어다 붙여** "확인된 용어를 바탕으로 도메인을 선택해 주세요" 같은 완전히 없는 단계를 지어냈습니다. 실제 상태머신(`conversation.py`)에는 그런 경로가 아예 없었으니 순수 렌더 단계 환각이었습니다 → **"N가지 경우" 목록을 만들 때는 반드시 전체 stage를 빠짐없이 나열**하세요. 일부만 나열하면 모델이 나머지를 "제일 비슷해 보이는 예시"로 즉흥 대체합니다 — 이것도 위 패턴의 변종이지만, "코드가 결정"이 아니라 "예시가 완전해야" 막을 수 있는 케이스라 따로 적어둡니다.

**새 기능에서 "N가지 경우에 따라 다르게 답해라" 류의 지시를 쓰게 되면, 위 패턴을 먼저 검토하세요**: (1) 판단에 필요한 중간값을 스키마 필드로 강제 선언, (2) 코드에서 그 필드로 최종값을 덮어쓰기, (3) 어떤 문장을 쓸지 자체를 코드가 정하고 모델은 다듬기만, (4) "이 중 하나" 류의 예시 목록은 실제로 나올 수 있는 값을 빠짐없이 나열.

## 실데이터 규모에서만 드러나는 버그 (2026-09-14, 실제 정부 데이터 13k+건 적재 후 발견)

시나리오용 합성 데이터는 도메인 4개, 용어 12개뿐이라 아래 문제들이 하나도 안 걸렸습니다. **"작게는 되는데 실제 규모에서 터지는" 클래스의 버그를 새로 만들지 않으려면, 코드에 "최대 N개"라는 가정이 있는지 항상 의심하세요** — 특히 여러 그룹/조건을 `limit`으로 각각 제한한 뒤 합치는 코드는 결과가 그 `limit`을 훌쩍 넘을 수 있습니다.

1. **`domain_usage()`가 30건 넘으면 무조건 예외** — `search()`가 정확일치/동의어/의미/철자 4개 그룹에서 각각 최대 30건씩 뽑아 합치는데(최악 120건), `domain_usage(similar_term_ids)`는 30건 초과 시 바로 `ValueError`. 합성 데이터일 땐 그룹 하나가 30건을 채울 수가 없어서 한 번도 안 터졌습니다. → `conversation.py`에서 넘기기 전에 `[:30]`으로 자름.
2. **약어 추천의 "기존 사례" 프롬프트가 OpenAI 요청 크기 초과(`BadRequestError`)** — `suggest_abbreviation()`이 기존 약어 전체를 프롬프트에 넣었는데, 13,000여 건에서 그대로 터졌습니다. → 이름 유사도(pg_trgm) 상위 200건만 추림. **일반화**: "카탈로그 전체를 프롬프트에 넣는다"는 코드는 전부 이런 잠재 버그를 안고 있다고 보고, 유사도/최신순 등으로 반드시 상한을 두세요.
3. **`registration.prepare()`의 정의 비교가 순차 호출이라 50~60초 소요** — 후보 최대 30~120건 각각에 `compare()`(OpenAI 호출 1회)를 순차 실행. 합성 데이터일 땐 후보가 몇 개뿐이라 안 느렸습니다. → `db.connect()`가 공유 커넥션/상태가 없어 스레드 간 안전하다는 걸 확인하고 `ThreadPoolExecutor(max_workers=8)`로 병렬화, 3~4초로 단축.
4. **퀵리플라이 버튼이 126개까지 뜸 — 같은 로직이 두 곳에 따로 구현돼 있었음** — 도메인 선택 단계에서 "증거 있는 도메인 + 나머지 전체 도메인"을 다 버튼으로 만들던 로직이 `app.js`(관리자 콘솔 표시용, 이번 세션에서 발견 후 수정)와 `build_chatflow.py`의 `render_context`(실제 챗봇 퀵리플라이 버튼, 완전히 별개의 코드베이스)에 **각각 독립적으로 구현**돼 있었습니다. 표만 고치고 챗봇 버튼 쪽을 놓쳤다가 사용자가 재차 지적해서 알아챘습니다. → 둘 다 "증거 있는 도메인 최대 10개, 없으면 전체 중 5개 폴백"으로 통일. **같은 규칙이 프론트엔드와 Dify 코드 노드에 중복 구현될 수 있다는 걸 항상 의심하세요** — 하나를 고치면 다른 쪽도 검색해서 확인.
5. **새 MCP 도구를 추가했는데 Dify가 못 찾음** (`Tool with name X not found`) — `tools.py`에 `@tool` 함수를 새로 추가한 뒤 챗플로우에서 바로 호출하면 이 에러가 납니다. 원인은 두 단계 다 필요하기 때문입니다: (1) 실행 중이던 MCP 서버 프로세스가 이미 떠 있으면 파이썬 코드를 다시 읽지 않으므로 **`cd term-standardization-mcp && ./start.sh --restart`로 재시작**해야 새 함수가 반영되고, (2) Dify는 도구 목록을 자기 DB에 캐싱해두므로 **`.venv/bin/python dify_admin.py mcp-register`로 재조회**해야 새 도구가 챗플로우에서 보입니다. 챗플로우 프롬프트만 고쳤을 땐(3단계 배포) 필요 없고, **도구 자체(함수 시그니처/개수)를 추가·변경했을 때만** 이 두 단계가 추가로 필요합니다.

## Dify 챗플로우 배포 — 반드시 3단계 순서

```bash
.venv/bin/python build_chatflow.py            # 1. YAML 재생성
.venv/bin/python dify_admin.py import dify-chatflow.yaml   # 2. 새 draft로 임포트
.venv/bin/python scripts/publish_chatflow.py  # 3. 방금 임포트한 draft를 배포
```

**1·2번을 빼고 3번만 실행하면, 직전에 임포트됐던(어쩌면 훨씬 이전) draft를 그대로 재배포하고 새 프롬프트 수정은 조용히 무시됩니다.** 이 세션에서 실제로 이 실수 때문에 "고쳤는데 왜 안 되지"를 몇 차례 반복했습니다. `STAGE_RULES`/`RENDER` 프롬프트를 고칠 때마다 위 3줄 전체를 다시 실행하세요. `setup_dify.py`(전체 설치 스크립트)는 이미 이 순서를 올바르게 구현하고 있습니다 — 문제는 항상 개발 중 수동으로 일부만 재실행할 때 발생했습니다.

검증은 curl로 SSE 스트림을 직접 까보는 게 가장 확실합니다:
```bash
curl -sN -X POST http://localhost:8090/v1/chat-messages \
  -H "Authorization: Bearer $(cat .runtime/chatflow-key.txt)" -H "Content-Type: application/json" \
  -d '{"query":"...","inputs":{},"response_mode":"streaming","user":"debug"}'
```
`node_finished` 이벤트 중 `node_id":"action"`의 `outputs.state`가 실제 MCP 상태이고, `node_id":"reply"`의 `process_data.prompts`로 실제 전달된 시스템/유저 프롬프트를 확인할 수 있습니다. `gpt-4o-mini`는 `temperature=0.1`(0 아님)이라 3회 이상 반복 확인하세요.

## `Caddyfile`을 고쳤으면 Caddy도 따로 재기동해야 합니다

`./start.sh --restart`는 MCP 서버(Python 프로세스)만 재시작합니다 — **Caddy는 완전히 별개의 프로세스라 그 재시작에 전혀 영향받지 않고, 자기가 시작될 때 읽은 `tools/Caddyfile` 설정을 계속 그대로 씁니다.** `poc-start.sh`/`poc-start.ps1`도 포트 8090이 이미 리스닝 중이면 "이미 실행 중"이라고 보고 건너뛰므로, 오래전에 띄워둔 Caddy가 그 뒤에 추가된 새 라우트(예: `admin_api.py`의 `/admin/*`)를 전혀 모른 채 계속 남아있을 수 있습니다.

실제로 이 문제로 겪은 사례(2026-09-16): 다른 세션에서 커밋한 `/admin/*` 라우트(설정 화면의 OpenAI/로컬 LLM 전환 API)를 pull하고 MCP 서버는 재시작했는데, 며칠 전부터 떠 있던 Caddy가 옛날 설정 그대로라 `/admin/llm-status` 호출이 계속 404 → 프론트엔드에서 "Unexpected end of JSON input" 에러로 나타났습니다. 백엔드 자체(`curl localhost:8100/admin/llm-status`)는 처음부터 정상이었어서, 원인 파악이 "프록시를 안 거치면 되는데 거치면 깨진다"는 것부터 시작해야 했습니다.

이 Caddyfile은 `{ admin off }`라 `caddy reload`(무중단 설정 리로드)도 안 됩니다 — 완전히 내렸다 다시 띄워야 합니다. 가장 안전한 방법은 전체 스택을 한 번 내렸다 올리는 것입니다:

```bash
# Mac/Linux
./poc-stop.sh && ./poc-start.sh
```
```powershell
# Windows
.\poc-stop.ps1; .\poc-start.ps1
```

**Caddyfile을 고칠 때마다(라우트 추가/변경) 이 절차를 거치세요** — MCP 코드만 바뀌었을 때의 `./start.sh --restart`와는 별개입니다.

## DB 시딩은 매 실행마다 자동 (idempotent) — 단, 실데이터는 수동 1회

`start.sh`/`start.ps1`이 `docker compose up`에 이어 매번 `manage.py init-db` → `import-catalog`(시나리오 12건) → `import-guideline`을 자동 실행합니다(커밋 `49beeb1`). DB는 `compose.yaml`의 `terms_data` Docker 볼륨이라 컴퓨터마다 독립이고, Mac↔Windows를 오가거나 새로 클론하면 매번 빈 상태로 시작하지만 위 자동 시딩 덕분에 즉시 시나리오 데이터가 채워집니다.

**실제 정부 표준 데이터(용어 13,168·단어 3,281·도메인 126)는 자동 시딩 대상이 아닙니다** — 원본 xlsx(data.go.kr "공공데이터 공통표준")는 `term-standardization-mcp/data/`에 저장소와 함께 커밋되어 있으므로, `manage.py import-standard-catalog "data/공공데이터 공통표준(2025.11월).xlsx"` 를 수동으로 1회(또는 data.go.kr에 새 개정판이 올라와 그 파일을 교체했을 때) 실행해야 합니다. 이 명령은:
- **재실행해도 안전**합니다(idempotent) — 이름+정의가 안 바뀐 행은 재임베딩도 안 하고 `updated_at`도 안 건드립니다(위 스케일 버그 절 참고 — `catalog_fingerprint()`가 모든 행의 `updated_at`을 해시하므로, 안 바뀐 행까지 건드리면 진행 중이던 모든 등록이 무효화됩니다).
- **폐기(deprecated) 행을 삭제하지 않고 `status='DEPRECATED'`로만 표시**합니다 — 이미 등록된 용어의 도메인 FK가 깨지지 않게. 모든 조회 경로(`search.py`/`conversation.py`/`tools.py`)는 `status='ACTIVE'`만 봅니다.
- 도메인 → 단어 → 용어 순으로 적재하고, 용어의 도메인 코드가 도메인 시트에 없으면(원본 데이터 불일치) 그 용어만 건너뛰고 개수를 보고합니다.

`registration_requests`/`word_registration_requests`/`conversation_state`(실제 등록 신청·대화 진행 상황)는 어느 쪽이든 시딩 대상이 아니라서 컴퓨터마다 따로 쌓입니다 — 데모용으로는 무해하지만 운영 환경이라면 별도 백업 전략이 필요합니다.

## 로컬 개발 시 브라우저 캐시 주의

`tools/Caddyfile`이 정적 프론트엔드에 `Cache-Control: no-cache` 헤더를 보내도록 되어 있습니다(원래 없었음, 커밋 `9b93c60`) — 이게 없으면 `style.css`/`app.js`를 고쳐도 브라우저가 예전 버전을 계속 보여줘서 "수정했는데 반영이 안 된다"처럼 보입니다. `index.html`의 `style.css?v=N`/`app.js?v=N` 쿼리스트링도 같은 이유로 붙어 있습니다 — **CSS/JS를 고칠 때마다 그 번호를 올리세요**(안 올려도 no-cache 덕분에 대부분 반영되지만, 과거 이 프로젝트에서 브라우저가 그래도 캐싱한 사례가 있어 이중 안전장치로 유지). `members.html`도 같은 `style.css`를 쓰므로 버전을 같이 올려야 합니다.

## 테스트 컨벤션

```bash
.venv/bin/python -m pytest -q                    # 기본: 유료 LLM 호출 0건 (스텁/결정론적 경로만)
RUN_LLM_TESTS=1 .venv/bin/python -m pytest -q    # 실제 OpenAI 호출 포함 (저비용이지만 유료)
```
`tests/test_business.py`에 테스트 71개(파라미터화 포함) — 기본 실행에서 65 passed / 6 skipped, `RUN_LLM_TESTS=1`이면 스킵된 6개도 마저 통과. 실LLM 테스트는 `@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1", ...)`로 게이팅되어 기본 실행에서 항상 스킵됩니다. 대화 흐름 테스트는 `conversation.suggest_definition`/`suggest_abbreviation`을 몽키패치해서 결정론적으로 검증하고, 실제 LLM 판단력 자체(예: 애매함 감지가 실제로 트리거되는지)는 `RUN_LLM_TESTS=1` 쪽에서만 검증합니다. **LLM 프롬프트 자체의 동작(Dify chatflow의 `STAGE_RULES`/`RENDER`)은 Python 유닛테스트로 검증 불가능** — 위 curl 방법이 유일한 검증 수단입니다.

`insert_standard_word(name, english_abbr, definition)` 헬퍼(`insert_guideline_chunk`와 동일한 패턴)로 테스트 DB에 최소 단어사전을 직접 심을 수 있습니다 — `standard_words`가 비어 있으면 `confirm_term`의 단어분해 체크 자체가 통째로 스킵되므로(아래), 그 분기를 테스트하려면 반드시 이 헬퍼로 최소 1개 이상 단어를 넣어야 합니다.

## 로컬 모델(Ollama) 테스트 지원 — 품질 타협은 절대 OpenAI 경로로 새지 않게

**목적을 먼저 이해하세요**: 이건 "제품을 로컬 모델로 바꾸는 작업"이 아니라 **"로컬 모델로도 서비스가 실제로 돌아가는가?"를 검증하는 실험**입니다. 여기서 유의미한 데이터가 쌓이면(품질은 충분한데 속도만 아쉽다 등) 하드웨어 증설을 검토할 근거가 됩니다. 이 목적 때문에, **테스트를 가능하게 하려고 넣은 타협이 OpenAI(프로덕션) 경로에 조용히 섞여 들어가면 안 됩니다** — 아래 항목들은 전부 `active_provider()=="local"`일 때만 적용되도록 짜여 있고, 코드에도 "TEST-ONLY" 주석이 달려 있습니다. 이 원칙을 어기는 변경은 하지 마세요.

**구성 요소**:
- `term_service/credentials.py`의 `active_provider()`/`set_active_provider()` — 관리자 UI(설정 화면)의 전환 버튼이 쓰는 런타임 스위치. `.runtime/llm_provider.json`을 매 호출마다 새로 읽어서 서버 재시작 없이 즉시 반영됩니다.
- `term_service/admin_api.py` — MCP 서버(8100)의 `/admin/llm-status`, `/admin/llm-provider`. POST 시 `build_chatflow.py → dify_admin.py import → publish_chatflow.py` 3단계를 서브프로세스로 실행해 Dify 챗플로우의 intent/reply 노드까지 같이 전환합니다(10~20초 소요).
- `credentials.llm_client()` — provider별로 타임아웃이 다릅니다(OpenAI 35초, 로컬 90초). 로컬 한 번의 생성이 35초 언저리에서 실패→재시도로 이어져 최대 70초 이상 날리는 걸 실측한 뒤 올렸습니다.
- `credentials.llm_extra_params()` — 로컬일 때만 `extra_body={"think": False}`를 얹습니다. Qwen3 같은 하이브리드 사고 모델은 구조화 출력(JSON 스키마)이 `<think>` 텍스트 자체는 걸러내도, 내부적으로 "생각"하는 시간 자체는 그대로 걸립니다.

**알려진 병목 — 로컬 GPU 1장은 OpenAI의 병렬 처리량을 못 따라감**: `registration.prepare()`가 후보 용어마다 `compare()`(LLM 1회 호출)를 돌리는데, OpenAI에서는 `ThreadPoolExecutor(max_workers=8)`가 진짜 병렬로 실행돼 3~4초에 끝나지만(위 "실데이터 규모" 절 3번 참고), 로컬은 GPU가 하나뿐이라 스레드 8개를 만들어도 사실상 순차 처리됩니다. 후보 12개짜리 확인 하나가 **Dify의 MCP 도구 호출 타임아웃(`sse_read_timeout=300`, 5분 — `dify_admin.py`의 `mcp-register` 참고)을 넘겨서, 에러 메시지 하나 없이 채팅이 그냥 멈추는 현상**으로 실제로 재현됐습니다(2026-09-15).

**테스트용 타협 — `LOCAL_COMPARE_CANDIDATE_CAP`**: 위 문제 때문에 `registration.py`의 `prepare()`는 `active_provider()=="local"`일 때만 `compare()` 대상을 상위 `LOCAL_COMPARE_CANDIDATE_CAP`(기본 5)개로 자릅니다. **이건 속도 최적화가 아니라 커버리지를 포기한 겁니다** — 캡 밖에 있는 진짜 중복 용어를 놓칠 수 있습니다(SAME_MEANING 거짓음성). 적용됐을 때는 `assessment.warnings`에 `LOCAL_TEST_COMPARISON_CAPPED`가 기록되니, 이 표시가 있는 신청 건은 사람이 전체 후보 목록을 다시 확인하기 전엔 승인하면 안 됩니다. **OpenAI 경로에는 이 캡이 절대 적용되지 않습니다** — 코드를 고칠 때 이 조건 분기를 무너뜨리지 마세요.

이 타협이 "OK, 이제 이렇게 계속 가자"로 굳어지는 걸 막으려면: 로컬 모델로 제품을 실제로 낼 계획이 생기면, 캡을 올리는 게 아니라 **애초에 LLM 호출 횟수 자체를 줄이는 방향**(후보들을 한 번의 호출에 묶어서 비교하는 등)으로 다시 설계해야 합니다.

## 알려진 미해결 이슈 / 다음 작업 후보

우선순위 순서는 아니고, 각자 다른 이유로 "PoC에서는 넘어갔지만 제품화하려면 반드시 다뤄야 하는" 항목들입니다.

1. **용어/단어/도메인 승인이 전부 CLI 전용 — 관리자 UI가 없음.** `manage.py approve-word`/`approve-term`/`approve-domain`(→ 각 모듈의 `approve()`)이 실제로 `PENDING_REVIEW`를 라이브 카탈로그로 승격시키는 유일한 경로입니다 — "승인 자체가 아예 없다"는 게 아니라 **관리자가 터미널 없이는 승인/반려를 못 한다**는 게 진짜 갭입니다. 이제 로그인/역할(아래 절)과 "회원 관리" 관리자 UI가 이미 있으니, 같은 화면에 용어/단어/도메인 승인 큐를 추가하는 게 자연스러운 다음 단계입니다.
2. ~~인증/권한이 없음~~ **(2026-09-16 해결)** — 아래 "로그인/세션/역할" 절 참고. 다만 완전히 메워진 건 아닙니다: 로그인은 `term-standardization-ui`(우리 프론트) 자체를 지킬 뿐, 프론트가 **Dify API를 직접(하드코딩된 키로) 호출하는 구조 자체는 그대로**입니다 — 그 키와 호출 방식을 아는 사람은 우리 로그인 화면을 거치지 않고도 Dify에 임의의 `user`(=`requester`) 값으로 직접 요청할 수 있습니다. 진짜로 막으려면 Dify 호출 자체를 우리 백엔드가 세션 검증 후 대신 호출해주는 프록시로 바꿔야 하는데, 이번 범위에서는 안 했습니다(아래 "로그인/세션/역할" 절의 "범위 밖" 참고).
3. **SEMANTIC_THRESHOLD(0.85)가 실측상 너무 타이트할 가능성.** "주간식단" 사례에서 진짜 관련 있는 기존 용어들이 임계값 바로 아래(0.82~0.84)에서 대량으로 걸러졌습니다. multilingual-e5-small의 코사인 유사도 분포 자체가 좁은 고구간에 몰리는 경향이 있어서, 카탈로그 전체에 대해 유사/비유사 쌍의 실제 분포를 뽑아 임계값을 재보정하는 작업이 필요합니다(아직 안 함). 실제 13k+ 데이터로도 이 경향이 재확인됐습니다 — 신규 단어 검색(`search_words()`)에서도 정답 단어가 0.855로 최상위가 아니라 5위 안팎에 걸리는 경우를 봤습니다.
4. **"라는"류 추출 버그는 LLM 프롬프트 레벨이라 근본적으로 불안정.** `naming.strip_trailing_particle`은 결정론적 조사(을/를/이/가/은/는) 제거만 하고, "정보라는" 같은 인용형 어미는 CLASSIFY 프롬프트의 few-shot 예시에만 의존합니다(`STAGE_RULES["awaiting_term_direct"]`). 이런 종류는 유닛테스트가 안 되므로, 비슷한 "자연어 패턴 의존" 버그를 새로 만나면 처음부터 결정론적 파싱으로 옮길 수 있는지부터 검토하세요.
5. **신규 단어 요청이 기존 단어를 재사용으로 찾아도 용어명 자체는 안 바뀜.** 위 "표준단어 계층" 절의 "알려진 한계" 참고 — "등본" 의미로 "증명서"를 찾아 재사용해도, 원래 용어명("등기부등본")엔 그 글자가 없어서 이후 약어 추천은 여전히 LLM이 즉석으로 지어냅니다. 용어명을 표준단어로 리네이밍하도록 권하는 기능은 없습니다.
6. **단어사전 검색이 정의 본문까지 부분일치로 훑어서 노이즈가 생김.** 예: "등본"으로 검색하면 그 글자를 우연히 정의에 포함한 무관한 단어("공부면적")가 나옵니다. 검색 정밀도 개선(이름 우선 가중치, 또는 이름/정의 검색을 분리) 여지가 있습니다.
7. **공개 URL(`poc-start.sh --public`)은 인증 없는 임시 cloudflare 터널.** 시연용으로만 쓰고, 이 방식 그대로 운영에 노출하면 안 됩니다.

## 자주 쓰는 명령

```bash
# 로컬 실행/재시작
./poc-start.sh                 # 최초/재시작 (idempotent)
./poc-start.sh --public        # + 임시 공개 URL 발급 (시연용)
./poc-stop.sh                  # 전체 종료(데이터 보존)

# MCP 서버만 재시작 (Python 코드 수정 후)
cd term-standardization-mcp && ./start.sh --restart

# 새 MCP 도구(@tool 함수)를 추가/변경했을 때 - 재시작 다음에 반드시 실행 (위 "실데이터 규모" 절 5번 참고)
cd term-standardization-mcp && .venv/bin/python dify_admin.py mcp-register

# 챗플로우 프롬프트 수정 후 (위 "3단계" 절 참고)
cd term-standardization-mcp
.venv/bin/python build_chatflow.py && .venv/bin/python dify_admin.py import dify-chatflow.yaml && .venv/bin/python scripts/publish_chatflow.py

# 목록조회 워크플로우(용어사전/단어사전/도메인관리 화면) 수정 후 - 1단계로 끝남
cd term-standardization-mcp && .venv/bin/python scripts/publish_list_terms_workflow.py

# 실제 정부 표준 데이터 적재/재동기화 (xlsx는 term-standardization-mcp/data/에 커밋되어 있음)
cd term-standardization-mcp && .venv/bin/python manage.py import-standard-catalog "data/공공데이터 공통표준(2025.11월).xlsx"

# 테스트
cd term-standardization-mcp && .venv/bin/python -m pytest -q

# DB 직접 조회 (DBeaver 등: 127.0.0.1:55432, DB terms, .env의 TERM_DB_PASSWORD)
docker exec -it term-standardization-database-1 psql -U terms -d terms
```
