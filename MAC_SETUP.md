# Mac 최초 설정 가이드

이 저장소는 Windows에서 만들어졌습니다. 코드는 그대로 옮겨왔지만, **Dify 안에 만들어둔 앱·지식베이스·API 키는 Windows Dify 내부 데이터라서 그대로 못 가져옵니다.** 아래 순서를 한 번만 밟으면, 그 뒤로는 Windows와 동일하게 `poc-start.sh` 한 줄로 실행할 수 있습니다.

전제: Docker Desktop이 이미 설치되어 있음 ("Mac에 Docker 설치" 세션에서 진행됨).

## 0. 폴더 구조

이 저장소와 Dify 저장소를 형제 폴더로 둡니다.

```
~/projects/
  term-standardization/   <- 이 저장소 (지금 보고 있는 곳)
  dify/                    <- 아래 1단계에서 새로 클론
```

## 1. Dify 새로 설치

```bash
cd ~/projects
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
```

`.env`에서 Windows 쪽에서 바꿨던 두 곳을 똑같이 적용합니다.

```bash
# .env 파일에서:
SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=host.docker.internal
```

그리고 `docker-compose.yaml`에서 `ENABLE_COLLABORATION_MODE=false`로 설정하고 `COMPOSE_PROFILES`에서 `collaboration`을 제거합니다 (실시간 협업 오버레이가 멈춰서 UI가 안 먹는 버그 회피).

```bash
docker compose up -d
```

몇 분 뒤 `http://localhost` 접속해서 최초 관리자 계정을 만듭니다.

## 2. MCP 서버 설정

```bash
cd ~/projects/term-standardization/term-standardization-mcp
cp .env.example .env
```

`.env`를 열어 `TERM_DB_PASSWORD`와 `DATABASE_URL`의 비밀번호를 새 값으로 채웁니다 (아무 임의 문자열이면 됩니다). `OPENAI_API_KEY`는 4단계에서 채웁니다.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

> kiwipiepy 설치 중 컴파일 오류가 나면 `xcode-select --install`로 Command Line Tools를 먼저 설치하세요.

```bash
chmod +x start.sh
./start.sh
```

`MCP ready: http://host.docker.internal:8100/mcp` 가 뜨면 성공입니다.

## 3. Dify에 MCP 서버 연결 (수동, 1회)

1. `http://localhost` → 스튜디오 → 아무 이름으로 **빈 Workflow 앱**을 하나 만듭니다.
2. 오른쪽 위 "도구" 또는 노드 추가에서 **MCP 서버 추가** — 이름 `term-standardization`, URL `http://host.docker.internal:8100/mcp`, 전송 방식 streamable-http.
3. 연결되면 19개 도구가 보입니다. 그중 하나(`analyze_morphology` 등)를 캔버스에 노드로 하나 끌어다 놓고 저장합니다 (도구 바인딩을 실제로 앱에 남겨야 다음 단계의 백업이 의미가 있습니다).
4. 주소창의 앱 URL에서 `app_id`를 확인합니다 — `http://localhost/app/<이 부분>/workflow` 형태입니다.

## 4. OpenAI 키 등록

스튜디오 우측 상단 계정 → 모델 공급자(Model Provider) → OpenAI에 실제 API 키를 붙여넣습니다. (Windows에서는 이 키를 DPAPI로 암호화해서 로컬에 보관했는데, DPAPI는 Windows 전용이라 Mac에서 복호화가 안 됩니다 — 그래서 새로 입력해야 합니다.) MCP 서버가 쓰는 `.env`의 `OPENAI_API_KEY`도 같은 키로 채웁니다.

## 5. 스크립트에 새 app_id 반영

`dify_admin.py` 맨 위 `PRELUDE` 안의 `App` id를 3단계에서 확인한 `app_id`로 바꿉니다.

```python
original=session.get(App,'여기에-3단계-app_id')
```

`link_dify_provider.py`도 쓸 계획이면 같은 방식으로 `app_id`를 바꿔주세요 (다만 4단계에서 이미 키를 직접 넣었다면 이 스크립트는 필요 없습니다).

## 6. 원본 백업 + 실제 앱 빌드

```bash
cd ~/projects/term-standardization/term-standardization-mcp
.venv/bin/python dify_admin.py backup
```

`backups/workflow-original.yaml`이 새로 생깁니다 (Mac Dify 테넌트 기준). 이제부터는 Windows에서 하던 것과 완전히 동일합니다.

```bash
.venv/bin/python build_chatflow.py
.venv/bin/python dify_admin.py import dify-chatflow.yaml
.venv/bin/python scripts/publish_chatflow.py

.venv/bin/python scripts/publish_list_terms_workflow.py
```

마지막 두 명령의 출력에 있는 `key` 값 두 개를 복사해 둡니다.

## 7. 지식베이스 재생성

```bash
.venv/bin/python sync_dify_knowledge.py
```

`data/scenario_catalog.json`의 "[가상]" 시나리오 문서 10건을 Dify 지식베이스로 새로 업로드하고, `.runtime/dify-knowledge.json`을 새로 씁니다.

## 8. 프론트엔드 키 교체

`term-standardization-ui/app.js` 상단의 두 상수를 6단계에서 복사해 둔 새 키로 바꿉니다.

```js
const DIFY_CHAT_KEY = "새 Chatflow 키";
...
const LIST_TERMS_KEY = "새 목록조회 Workflow 키";
```

## 9. Caddy · cloudflared 설치

```bash
brew install caddy cloudflared
```

(Windows에서는 `tools/caddy.exe`, `tools/cloudflared.exe`를 직접 내려받았지만, Mac은 Homebrew가 표준입니다. `tools/Caddyfile`은 그대로 씁니다 — 경로가 하드코딩되어 있지 않고 `poc-start.sh`가 넘겨주는 `UI_DIR` 환경변수를 읽도록 이미 되어 있습니다.)

## 10. 실행

```bash
cd ~/projects/term-standardization
chmod +x poc-start.sh poc-stop.sh
./poc-start.sh            # 로컬만: http://localhost:8090
./poc-start.sh --public   # 외부 공개 URL까지 발급
./poc-stop.sh             # 전체 종료 (데이터 보존)
```

## 참고: DB 데이터는 새로 시작합니다

Windows 쪽에 실제로 등록됐던 용어 데이터는 이전하지 않기로 했습니다. `start.sh`가 `manage.py init-db`로 스키마만 만들고, 도메인 코드(수N7 등)와 기본 카탈로그는 비어 있는 상태로 시작합니다. 시나리오 데모용 데이터가 필요하면 term-standardization-mcp의 README/DESIGN 문서에 있는 초기 데이터 적재 절차를 참고하세요.
