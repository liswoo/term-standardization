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

## "표준 데이터 조회" 신청 탭: 용어/단어/도메인 간편 입력 + AI 대화, 두 경로 (2026-09-17)

"표준 데이터 조회" 화면 상단에 조회/용어 신청/단어 신청/도메인 신청 4개 탭을 추가했습니다(독립 화면이던 "도메인 신청"도 이 탭으로 흡수). 용어/단어 신청 탭은 사용자가 **간편 입력(폼 한 번 제출)** 과 **AI와 대화하며 등록(기존 챗봇 재사용)** 중 하나를 고를 수 있습니다 — 둘 다 제공하기로 한 이유는, 도메인과 달리 용어/단어 등록은 원래부터 임베딩 기반 중복탐지·가이드라인 준수(LLM)·표준단어 완전분해가 필수로 얽혀 있어 챗봇 대화로만 가능했고, 그 다단계 판단을 버리면 품질 검증이 약해지기 때문입니다.

- **간편 입력의 정체**: 새 `POST /admin/term-requests`/`POST /admin/word-requests`(`admin_api.py`)는 `registration.py`/`word_registration.py`의 `prepare()`/`submit()`을 **그대로** 위임합니다 — 즉 챗봇 경로와 똑같은 임베딩+LLM 의미비교·가이드라인 검사를 거칩니다. 다단계 안내(재시도 유도, 정의 제안 등) 없이 첫 실패 사유를 그 자리에서 에러로 보여주는 점만 다릅니다. 용어 쪽은 새 `quick_registration.py`가 conversation.py의 confirm_term이 하던 **표준단어 gap 체크**(`naming.segment_words`/`unmatched_spans`)만 별도로 재현해서, 챗봇의 단어등록 서브플로우 없이는 처리 못 하는 이름을 `WORD_GAP_REQUIRES_REGISTRATION`으로 먼저 걸러냅니다(안 걸러내면 어떤 부분이 새 표준단어가 필요한지 아무도 모른 채 그냥 등록되어 버립니다). 단어 신청은 원래도 exact-match만 확인하는 단순 경로라 별도 모듈 없이 `word_registration.py`를 그대로 씀 — 도메인과 동급 난이도.
- **AI 대화 경로는 새로 만들지 않았습니다**: "대화로 등록 시작" 버튼은 그냥 기존 플로팅 챗봇을 열고(`openChat()`) `submitChatMessage("용어를 등록할래요")`(단어는 "단어를 등록할래요")를 대신 보낼 뿐입니다 — 이미 검증된 챗봇 플로우를 그대로 재사용.
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

- **`GET /admin/term-requests/check-name`**: `validate_name()`(형식) → `registration.find_pending()`(대기 중 중복) → `search()`(EXACT_MATCH/SYNONYM_MATCH, 임베딩만 - LLM 없음)를 이 순서로 검사. `registration.prepare()`를 여기서 재사용하지 않은 이유: LLM 기반 SAME_MEANING 비교까지 돌리면 blur 한 번에 수 초가 걸리고 `registration_preparations`에 부작용 있는 행까지 남김 — 그 더 깊은 의미 판단은 여전히 최종 제출 시점의 몫(기존과 동일, 퇴보 아님). `tr-term-name`의 `blur` 이벤트에서 호출 → 통과 시 초록 테두리, 실패 시 빨강 테두리 + 사유 문구(`app.js`의 `setFieldState()`).
- **`GET /admin/term-requests/suggest-definition`**: 이름이 "사용 가능" 판정을 받은 직후 자동 호출 - 버튼 없음. 구체적 정의가 나오면 클릭해서 적용하는 카드(`.field-suggestion-chip`)로, 모호하면(질문+후보) 클릭형 옵션 버튼으로 보여줌 - 둘 다 적용 전까지는 `tr-definition`을 건드리지 않음(챗봇 카드와 같은 "제안 vs 자동적용" 원칙).
- **`GET /admin/term-requests/suggest-followups`**: 이름 통과 + 정의 입력(제안 클릭 또는 직접 작성 후 blur) 시점에 도메인 추천(`domain_usage()`)과 영문약어 추천(`suggest_abbreviation()`)을 한 번에 묶어 호출. **도메인/영문약어 필드가 비어있을 때만** 값을 채워넣음(사용자가 이미 직접 입력한 값은 절대 덮어쓰지 않음) - 추천 근거는 필드 아래 회색 문구로만 표시(`.field-suggestion-note`), "직접 입력해 바꿀 수 있습니다"라고 항상 안내. 도메인 추천이 채워지면 기존 `populateTermDomainDerivedFields()`(허용값/표현형식/저장형식 참고 표시)도 자동으로 같이 실행됨.

프론트는 매 비동기 호출마다 fetch-token(예: `termNameCheckToken`)으로 낡은 응답이 최신 입력을 덮어쓰지 않게 막음 - `populateTermDomainDerivedFields()`의 기존 `termDomainDerivedFetchToken` 패턴과 동일. 브라우저로 직접 확인(2026-09-21): 기존 용어명 입력 → 빨강 테두리+"이미 등록된 표준용어입니다" 즉시 표시, 신규 이름 → 초록 테두리 → 정의 추천 카드 등장 → 클릭 시 도메인("수N7", 비교군 43% 사용)·영문약어("DAILY_MST_INTK", 조합 근거 포함) 자동 채움까지 실제 동작 확인.

**배포 직후 실사용자가 바로 잡아낸 버그 둘**:
1. **모호함 질문의 안내문구·버튼이 겹침** — `.field-suggestion-note`/`.field-suggestion-options`가 둘 다 음수 `margin-top`을 쓰고 있어서(다른 곳에서 입력창 바로 아래에 붙일 땐 의도한 효과였지만, 여기서는 두 요소가 연달아 있어 음수가 누적됨) 질문 문장과 선택 버튼이 거의 겹쳐 보였음. 전용 클래스 `.field-suggestion-question`을 새로 만들어 양의 여백으로 교체.
2. **후보 버튼을 클릭하면 그 라벨이 그대로 정의로 들어감** — "변경 이후에 할당된 주소 코드"라는 후보 라벨은 "이 의미가 맞다"는 답일 뿐 완성된 정의 문장이 아닌데, 그대로 `tr-definition`에 꽂아 넣고 있었음. 챗봇의 `set_definition`이 옵션 선택을 절대 정의 자체로 취급하지 않고 `clarification_history`에 답을 추가해 `suggest_definition()`을 다시 부르는 것과 똑같이 고침 — `suggest-definition` 라우트가 이제 `clarification_history`(JSON 쿼리 파라미터) 를 받아 `suggest_definition()`에 그대로 전달하고, 프론트는 후보 클릭 시 이 라운드트립을 거쳐 받은 진짜 정의 문장을 적용함(이미 한 번 선택이라는 의사표시를 했으므로 추가 클릭 요구 없이 바로 반영). fetch를 모킹해 모호함→후보 클릭→완성된 정의 문장 반영까지 결정론적으로 재현해 확인(LLM이 항상 모호하게 답하진 않아 실제 API로는 재현이 들쭉날쭉했음).

**실 배포 후 curl 대신 진짜 `/v1/chat-messages` 스트리밍으로 처음부터 끝까지 3회 검증**(단어 갭 있는 용어 → 도메인 전체 거절 → 신규 스펙 초안 → PII 질문 → 약어 → 최종 등록 → `manage.py approve-domain` → 용어 자동 `PENDING_REVIEW` 승격까지 실제 DB에서 확인) 하는 과정에서 **이번 작업과 무관한 기존 버그**를 하나 발견: `set_word_abbreviation`이 `word_registration.submit()`의 `PENDING_REQUEST_ALREADY_EXISTS`(같은 이름의 단어가 다른 대화에서 이미 대기 중일 때)를 처리하지 않고 `term_pending_words`에 아무것도 추가하지 않은 채 그냥 용어 흐름을 재개시켜버립니다 — 그 결과 용어가 실제로는 미승인 단어에 의존하면서도 의존성 추적 없이 곧장 `PENDING_REVIEW`로 제출됩니다. pytest는 매 테스트마다 `word_registration_requests`를 비우는 `terms_test` DB를 써서 이 경로를 한 번도 못 건드렸습니다 — 이번 세션에서 같은 신규 단어("간편")로 반복 테스트하다가 실제 개발 DB에서 처음 걸림. 별도 작업으로 남겨둠(수정 안 함) — 다음에 다룰 때는 `set_word_abbreviation`의 `result.get("request_id")` 체크와 `_resume_or_finish_word_flow`가 성공/실패를 구분 안 하는 지점부터 보세요.

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
