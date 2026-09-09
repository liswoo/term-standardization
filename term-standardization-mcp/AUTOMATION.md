# Dify 자동화 유지보수 가이드

`setup_dify.py`와 `dify_admin.py`가 새 설치마다 Dify Studio를 손으로 클릭하던 과정(빈 앱 생성 → MCP 서버 추가 → 도구 드래그 → 저장, OpenAI 키 붙여넣기)을 대신합니다. 이 문서는 **설치 방법이 아니라**, 새 에이전트(Dify 앱)를 추가하거나 기존 앱을 바꿀 때 이 자동화를 어떻게 고쳐야 하는지를 다룹니다. 설치 자체는 [../SETUP.md](../SETUP.md)를 보세요.

## 왜 이렇게 만들었는가

Dify Studio에서 MCP 도구를 캔버스에 드래그하면 워크플로우 노드에 `provider_id`, `provider_name`, `provider_icon` 같은 필드가 저장됩니다. 이 값들은 Dify가 서버에서 생성하는 게 아니라, **MCP 서버를 등록할 때 우리가 직접 입력한 문자열이 그대로 복사된 것**입니다 (`dify_mcp_config.py`의 `MCP_PROVIDER_FIELDS`). 그래서 UI에서 매번 긁어올 필요가 없고, 코드에 고정값으로 박아두면 됩니다. 이 사실이 전체 자동화의 전제입니다 — Dify 내부 구현이 바뀌어 이 값들이 서버 생성 UUID 등으로 바뀌면 이 전제가 깨집니다 (아래 "Dify 버전이 바뀌면" 참고).

## 구성 요소

| 파일 | 역할 |
|---|---|
| `dify_mcp_config.py` | MCP 제공자 식별자·아이콘 등 고정값. 여기 값을 바꾸면 등록된 MCP 서버 이름/식별자도 바뀝니다 (재등록 필요, 아래 참고). |
| `templates/dify_app_base.yaml` | 모든 생성 앱의 뼈대(app 메타데이터, `workflow.features` 기본값). Studio에서 새 앱을 만들 때 Dify가 채워주는 기본값의 스냅샷입니다. |
| `dify_admin.py` | Dify 내부 서비스를 `docker exec`로 호출하는 저수준 유틸. `PRELUDE`가 테넌트 오너 계정을 자동으로 찾아 `tenant_id`/`account`를 준비해두므로, 이 파일을 쓰는 모든 스크립트는 이 두 변수를 바로 쓸 수 있습니다. 액션: `import`(DSL 임포트, 이름으로 기존 앱 찾아 갱신), `mcp-register`, `openai-credential`. |
| `build_chatflow.py`, `build_list_terms_workflow.py` | 각 앱의 실제 노드 그래프(YAML DSL)를 파이썬으로 조립. |
| `scripts/publish_*.py` | 빌드된 YAML을 임포트하고, 워크플로우를 배포(publish)하고, 프론트엔드용 API 키를 발급. |
| `setup_dify.py` | 위 전부를 올바른 순서로 실행하는 오케스트레이터. **파라미터 없음** — 필요한 값은 전부 `.env`/기존 파일에서 읽습니다. |

## 새 에이전트(Dify 앱)를 추가하려면

1. `build_<name>.py`를 `build_chatflow.py`를 본떠서 작성합니다:
   - `templates/dify_app_base.yaml`을 베이스로 deep-copy
   - `dify_mcp_config.MCP_PROVIDER_FIELDS`로 MCP 도구 노드 구성 (필요한 도구만 `tool(id, tool_name, params)`로 추가 — 이미 등록된 MCP 서버의 19개 도구 중 아무거나 이름으로 지정하면 됩니다, Studio에서 다시 등록할 필요 없음)
   - `doc["app"]["name"]`을 고유한 이름으로 지정 — **이 이름이 idempotency의 기준**입니다. `dify_admin.py import`가 캐시 파일이 없을 때 이 이름으로 기존 앱을 찾아 갱신하므로, 이름을 바꾸면 새 앱이 생성됩니다.
2. 배포 스크립트를 만듭니다. 대화 상태가 있는 Chatflow라면 `dify_admin.py import` + 별도 `scripts/publish_<name>.py`(→ `scripts/publish_chatflow.py` 참고), 단순 1회성 Workflow라면 `scripts/publish_list_terms_workflow.py`처럼 빌드+임포트+배포를 한 스크립트에 합쳐도 됩니다.
3. `setup_dify.py`의 `main()`에 실행 순서를 추가합니다. **지식베이스가 필요한 앱이면 `sync_dify_knowledge.py` 실행 이후에 두세요** — `build_chatflow.py`가 `.runtime/dify-knowledge.json`의 `dataset_id`를 참조하기 때문에 순서가 반대면 실패합니다.
4. 앱이 API 키를 프론트엔드에 노출해야 한다면, `patch_app_js()`에 새 키 자리를 추가하거나(같은 패턴으로 `re.subn`) 별도 함수를 씁니다.

## 새 MCP 도구를 기존 앱에 추가하려면

Studio 조작 없이, 해당 `build_*.py`에 `tool("새_노드_id", "mcp_도구_이름", {파라미터...})` 한 줄만 추가하면 됩니다. MCP 서버가 그 이름의 도구를 실제로 제공하는지는 `dify_admin.py mcp-register`가 이미 등록해둔 프로바이더의 도구 목록(Studio의 연동 → MCP 화면, 또는 `list_provider_tools`)에서 확인하세요.

## Idempotency 규칙 (지켜야 재실행이 안전합니다)

- **이름/식별자로 기존 리소스를 먼저 찾고, 없을 때만 생성한다.** MCP 프로바이더는 `server_identifier`, 앱은 `App.name`, OpenAI 자격증명은 "현재 활성 자격증명 존재 여부", 지식베이스 문서는 "같은 제목의 문서 존재 여부"로 판단합니다. 새 리소스 종류를 추가할 때도 이 패턴을 따르세요.
- `.runtime/*.json` 캐시 파일은 **속도를 위한 지름길일 뿐, 정합성의 원천이 아닙니다.** 캐시가 없거나(다른 컴퓨터, `.runtime/` 삭제) 오래됐어도 이름 기반 조회가 항상 폴백으로 동작해야 합니다 (`dify_admin.py`의 `import` 액션 참고).
- 무언가를 "이미 있으면 덮어쓸지 건드리지 않을지" 결정할 때는, **API 키처럼 다른 곳(프론트엔드 `app.js`, 이 앱을 쓰는 사람)이 이미 참조 중인 값은 함부로 재발급하지 않습니다.** (예: OpenAI 자격증명은 이미 있으면 손대지 않음. 앱은 새로 만들지 않고 같은 app_id로 갱신 — 발행할 때마다 워크플로우 버전만 올라가고 API 키는 유지됩니다.)

## 변경 사항 검증 방법

로컬에 이미 떠 있는 인스턴스(개발용)에 대해 그냥 다시 돌려보는 게 가장 확실합니다:

```bash
.venv/bin/python setup_dify.py
```

- Dify Studio(`http://localhost/apps`)에서 앱 개수가 **늘어나지 않았는지** 확인 (같은 이름 앱이 중복 생성되면 이름 기반 매칭이 실패한 것)
- 연동 → MCP 화면에서 프로바이더가 여전히 하나뿐인지 확인
- `term-standardization-ui/app.js`의 키가 이전 실행과 **같은 값**으로 남아있는지 확인 (`git diff term-standardization-ui/app.js`로 확인 — 바뀌었다면 앱이 의도치 않게 재생성된 것)
- 실제 채팅(`http://localhost:8090`)으로 한 번 대화해서 MCP 도구 호출까지 살아있는지 확인

## Dify 버전이 바뀌면 (중요)

이 자동화는 Dify의 **내부 서비스 API**(`services.app_dsl_service.AppDslService`, `services.tools.mcp_tools_manage_service.MCPToolManageService`, `services.model_provider_service.ModelProviderService`, `models.account.TenantAccountJoin` 등)를 직접 import해서 씁니다. 이건 Dify가 공개적으로 안정성을 보장하는 REST API가 아니라 **내부 구현**이라, Dify 버전을 올리면 함수 시그니처나 클래스 위치가 바뀌어 조용히 깨질 수 있습니다.

이 문서를 쓸 당시 기준은 Dify `1.17.0`(커밋 `0df092d3c7`)이고, [SETUP.md](../SETUP.md)가 클론하는 `liswoo/dify` 포크가 정확히 이 커밋에 고정되어 있습니다. **업그레이드는 항상 의도적으로**, 포크에서 `git fetch upstream && git merge upstream/main`으로 진행하고, 아래 확인을 거친 뒤에만 포크의 `main`에 반영하세요 (그래야 다른 사람이 그사이 `git clone`해도 검증 안 된 버전을 받는 일이 없습니다).

Dify를 업그레이드했다면:
1. `.venv/bin/python setup_dify.py`를 한 번 돌려서 각 단계가 에러 없이 끝나는지 확인합니다. `dify_admin.py`의 `execute()`가 예외를 그대로 올려주므로 어느 서비스 호출이 깨졌는지 스택트레이스로 바로 보입니다.
2. 특히 `PRELUDE`의 `TenantAccountJoin`/`TenantAccountRole` 조회, `mcp-register`의 `MCPToolManageService.create_provider`/`reconnect_with_url` 시그니처, `openai-credential`의 `ModelProviderService.get_provider_credential`/`create_provider_credential` 시그니처를 Dify 소스(`../dify/api/`)에서 다시 확인하세요.
3. 문제없이 통과하면 `git push origin main`으로 포크에 반영하고, 이 문서의 버전/커밋 표기와 `SETUP.md`도 같이 갱신하세요.
3. 고칠 때는 REST 콘솔 API 컨트롤러(`controllers/console/...`)가 같은 서비스를 어떻게 호출하는지 참고하는 게 가장 빠릅니다 — 우리가 흉내내야 할 "정답 동작"이 바로 그 코드입니다.
