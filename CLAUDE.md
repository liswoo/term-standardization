# CLAUDE.md — 용어표준화 AI 에이전트

이 문서는 새 세션(에이전트든 사람이든)이 이 저장소에 처음 들어왔을 때 가장 먼저 읽는 문서입니다. **"무엇을 만들었는가"보다 "왜 이렇게 만들었는가"와 "다음에 뭘 조심해야 하는가"에 집중**합니다. 파일별 세부 계약은 [term-standardization-mcp/DESIGN.md](term-standardization-mcp/DESIGN.md), 설치는 [SETUP.md](SETUP.md), Dify 자동화 내부 구조는 [term-standardization-mcp/AUTOMATION.md](term-standardization-mcp/AUTOMATION.md)를 보세요. 이 문서는 그 셋을 대체하지 않고 연결합니다.

## 지금 상태: PoC → Product 전환 중

2026-09-08~11 사이 세션들에서 등록 대화 흐름의 핵심 기능(가이드라인 RAG 검사, 영문약어 추천, 정의 추천, 도메인 추천, UI 표/카드화)이 갖춰졌고, 여러 신뢰성 버그를 실제 재현·검증하며 고쳤습니다. **아직 PoC입니다** — 아래 "제품화 전 반드시 메워야 할 공백" 절을 먼저 읽으세요. 데이터는 전부 `SYNTHETIC_SCENARIO_V1_NOT_OFFICIAL` 가상 데이터(`data/scenario_catalog.json`, `data/standard_guide.md`)이고, 실제 공공기관 표준이 아닙니다.

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
- MCP 서버가 22개 도구를 노출하고, Dify Chatflow(`용어표준화-대화형`)가 사용자 메시지를 해석해 그 도구들을 호출합니다. **업무 판단과 저장의 기준은 항상 MCP**이고, Dify의 LLM 노드는 의도 해석과 답변 문장 생성만 담당합니다.

## 대화 상태머신 (`term_service/conversation.py`)

`transition(state, action, ...)`이 순수 함수로 모든 단계 전이를 결정합니다. Dify는 사용자 메시지를 `{intent, value, confirmed}`로만 해석해서 넘기고, 실제 유효성 검사·중복 판정·저장은 전부 이 함수와 그 안에서 호출하는 모듈이 합니다.

**현재 단계 순서** (2026-09-10에 의도적으로 재배치됨):

```
propose_term → awaiting_term_confirm → confirm_term
  → (EXACT_MATCH/SYNONYM_MATCH) → existing_term_found  [종료]
  → (검토 대기 중복) → pending_request_found  [종료]
  → (형태소/가이드라인 위반) → awaiting_guideline_choice → propose_term로 재시도
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

## 두 개의 독립된 벡터/RAG 시스템 — 절대 섞지 마세요

1. **MCP 자체 pgvector** (`term_service/embeddings.py`, `search.py`, `guideline.py`) — `standard_terms`(용어 유사도/중복 판정)와 `guideline_chunks`(`standard_guide.md`를 벡터화, 가이드라인 준수 검사·약어 추천·정의 추천의 근거)를 담당. **이게 업무 판단의 기준**입니다.
2. **Dify 자체 지식베이스** (`sync_dify_knowledge.py`가 Weaviate에 업로드) — `show_candidates`/`help` 의도일 때만 참고 자료로 노출되는 보조 지식. **업무 판단에 관여하지 않습니다.**

두 시스템 다 같은 소스 파일(`scenario_catalog.json`, `standard_guide.md`)에서 만들어지지만 완전히 별개의 인덱스이므로, 하나를 고치고 다른 쪽 재동기화를 잊으면 데이터가 어긋납니다. MCP 쪽은 `manage.py import-catalog`/`import-guideline`(start.sh/ps1이 매번 자동 실행), Dify 쪽은 `sync_dify_knowledge.py`(setup_dify.py 3단계, 자동 재실행 안 됨 — 문서 내용을 바꿨으면 수동으로 다시 돌려야 함).

## 반복해서 발견한 엔지니어링 패턴: "작은 모델에게 부탁하지 말고, 코드가 결정하게 하라"

`CLASSIFY_MODEL = gpt-4o-mini`(비용 때문에 의도적으로 저사양 모델 사용, `build_chatflow.py` 상단 참고)로 이 세션 내내 반복된 실패 패턴이 있습니다: **"이 데이터가 있으면 이렇게, 없으면 저렇게 말해라" 같은 조건부 지시를 프롬프트로만 주면 모델이 자꾸 무시하거나 잘못된 분기를 탑니다.** 매번 같은 방식으로 고쳤고, 새 기능을 붙일 때도 이 패턴을 기본으로 쓰세요:

- **가이드라인 검사** (`guideline.py`): "정확히 이 단어와 문자열이 같을 때만 위반"이라고 프롬프트로 아무리 강조해도 모델이 "느낌상 포괄적이다"로 위반 처리했습니다 → `matched_forbidden_word`를 `compliant`보다 먼저 선언한 필드로 만들어 강제로 먼저 답하게 하고, **코드에서 `matched_forbidden_word != term_name`이면 `compliant`를 강제로 덮어씀**(모델이 뭐라 답하든 무시).
- **도메인/비교 표 중복 방지** (`build_chatflow.py`의 `render_context`): "화면에 표로 보여주니 문장에서 반복하지 마라"라고 지시해도 모델이 `business_result.state`에 원본 데이터가 남아있으면 그대로 베껴 썼습니다 → **표/카드로 대체되는 원본 데이터를 아예 `{"note": "..."}`로 마스킹해서 모델 프롬프트에서 보이지 않게 함.** 옵션 라벨(도메인 설명 등 긴 텍스트를 담음)도 `context` JSON에서 분리해 별도 output 필드로 빼서, reply LLM 프롬프트에는 아예 노출되지 않게 했습니다.
- **정의 안내 문구 선택** (`definition_hint`): "제안이 있으면/없으면/질문이면" 세 가지 문구 중 하나를 플래그 보고 고르라고 시켰더니 계속 틀렸습니다(불리언 2개 조합 분기는 모델에게 너무 어려움) → **어떤 문장을 써야 하는지 자체를 파이썬 코드에서 결정**(`definition_hint`/`existing_match_hint` 변수)하고, 모델은 그 문장을 자연스럽게 다듬어 전달하는 역할만 하게 축소.

**새 기능에서 "N가지 경우에 따라 다르게 답해라" 류의 지시를 쓰게 되면, 위 패턴을 먼저 검토하세요**: (1) 판단에 필요한 중간값을 스키마 필드로 강제 선언, (2) 코드에서 그 필드로 최종값을 덮어쓰기, (3) 어떤 문장을 쓸지 자체를 코드가 정하고 모델은 다듬기만.

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

## DB 시딩은 매 실행마다 자동 (idempotent)

`start.sh`/`start.ps1`이 `docker compose up`에 이어 매번 `manage.py init-db` → `import-catalog` → `import-guideline`을 자동 실행합니다(커밋 `49beeb1`). DB는 `compose.yaml`의 `terms_data` Docker 볼륨이라 컴퓨터마다 독립이고, Mac↔Windows를 오가거나 새로 클론하면 매번 빈 상태로 시작하지만 위 자동 시딩 덕분에 즉시 시나리오 데이터가 채워집니다. `registration_requests`/`conversation_state`(실제 등록 신청·대화 진행 상황)는 시딩 대상이 아니라서 컴퓨터마다 따로 쌓입니다 — 데모용으로는 무해하지만 운영 환경이라면 별도 백업 전략이 필요합니다.

## 로컬 개발 시 브라우저 캐시 주의

`tools/Caddyfile`이 정적 프론트엔드에 `Cache-Control: no-cache` 헤더를 보내도록 되어 있습니다(원래 없었음, 커밋 `9b93c60`) — 이게 없으면 `style.css`/`app.js`를 고쳐도 브라우저가 예전 버전을 계속 보여줘서 "수정했는데 반영이 안 된다"처럼 보입니다. `index.html`의 `?v=2` 쿼리스트링도 같은 이유로 붙어 있습니다. 프론트엔드 리소스를 더 추가하면 캐시 버스팅 여부를 같이 고려하세요.

## 테스트 컨벤션

```bash
.venv/bin/python -m pytest -q                    # 기본: 유료 LLM 호출 0건 (스텁/결정론적 경로만)
RUN_LLM_TESTS=1 .venv/bin/python -m pytest -q    # 실제 OpenAI 호출 포함 (저비용이지만 유료)
```
`tests/test_business.py`에 31개 테스트. 실LLM 테스트는 `@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1", ...)`로 게이팅되어 기본 실행에서 항상 스킵됩니다. 대화 흐름 테스트는 `conversation.suggest_definition`/`suggest_abbreviation`을 몽키패치해서 결정론적으로 검증하고, 실제 LLM 판단력 자체(예: 애매함 감지가 실제로 트리거되는지)는 `RUN_LLM_TESTS=1` 쪽에서만 검증합니다. **LLM 프롬프트 자체의 동작(Dify chatflow의 `STAGE_RULES`/`RENDER`)은 Python 유닛테스트로 검증 불가능** — 위 curl 방법이 유일한 검증 수단입니다.

## 알려진 미해결 이슈 / 다음 작업 후보

우선순위 순서는 아니고, 각자 다른 이유로 "PoC에서는 넘어갔지만 제품화하려면 반드시 다뤄야 하는" 항목들입니다.

1. **관리자 승인/반려 플로우가 아예 없음.** `registration_requests.status`는 `PENDING_REVIEW`/`APPROVED`/`REJECTED` 세 값을 스키마에 정의해뒀지만, **PENDING_REVIEW에서 벗어나는 코드 경로가 전혀 없습니다.** 신청은 계속 쌓이기만 하고 표준사전(`standard_terms`)으로 승격되지도, 반려되지도 않습니다. 이게 PoC와 제품의 가장 큰 간극입니다 — 승인 워크플로우(누가, 어떤 권한으로, 승인 시 `standard_terms` INSERT + 지식베이스 재동기화까지)를 설계해야 합니다.
2. **인증/권한이 없음.** `requester`는 그냥 신뢰된 문자열입니다(Dify가 넘겨주는 `sys.user_id`). 누구나 아무 이름으로 신청·조회할 수 있고, 신원 확인이나 역할 구분이 없습니다.
3. **SEMANTIC_THRESHOLD(0.85)가 실측상 너무 타이트할 가능성.** "주간식단" 사례에서 진짜 관련 있는 기존 용어들이 임계값 바로 아래(0.82~0.84)에서 대량으로 걸러졌습니다. multilingual-e5-small의 코사인 유사도 분포 자체가 좁은 고구간에 몰리는 경향이 있어서, 카탈로그 전체에 대해 유사/비유사 쌍의 실제 분포를 뽑아 임계값을 재보정하는 작업이 필요합니다(아직 안 함 — 사용자가 "일단 순서 바꾸기부터"를 택함).
4. **"라는"류 추출 버그는 LLM 프롬프트 레벨이라 근본적으로 불안정.** `naming.strip_trailing_particle`은 결정론적 조사(을/를/이/가/은/는) 제거만 하고, "정보라는" 같은 인용형 어미는 CLASSIFY 프롬프트의 few-shot 예시에만 의존합니다(`STAGE_RULES["awaiting_term_direct"]`, 커밋 `82d7e7a` 배경 세션에서 별도 백그라운드 작업으로 부분 수정됨). 이런 종류는 유닛테스트가 안 되므로, 비슷한 "자연어 패턴 의존" 버그를 새로 만나면 처음부터 결정론적 파싱으로 옮길 수 있는지부터 검토하세요.
5. **실데이터 전환 계획이 없음.** 지금은 전부 `SYNTHETIC_SCENARIO_V1_NOT_OFFICIAL` 표시가 붙은 가상 데이터(`data/scenario_catalog.json`, 12건)입니다. 실제 기관 표준사전으로 바꿀 때 `manage.py import-catalog`가 그대로 쓸 수 있는 형식이긴 하지만, 기존 승인 이력이나 개정 이력을 어떻게 가져올지는 설계된 바 없습니다.
6. **공개 URL(`poc-start.sh --public`)은 인증 없는 임시 cloudflare 터널.** 시연용으로만 쓰고, 이 방식 그대로 운영에 노출하면 안 됩니다.

## 자주 쓰는 명령

```bash
# 로컬 실행/재시작
./poc-start.sh                 # 최초/재시작 (idempotent)
./poc-start.sh --public        # + 임시 공개 URL 발급 (시연용)
./poc-stop.sh                  # 전체 종료(데이터 보존)

# MCP 서버만 재시작 (Python 코드 수정 후)
cd term-standardization-mcp && ./start.sh --restart

# 챗플로우 프롬프트 수정 후 (위 "3단계" 절 참고)
cd term-standardization-mcp
.venv/bin/python build_chatflow.py && .venv/bin/python dify_admin.py import dify-chatflow.yaml && .venv/bin/python scripts/publish_chatflow.py

# 테스트
cd term-standardization-mcp && .venv/bin/python -m pytest -q
```
