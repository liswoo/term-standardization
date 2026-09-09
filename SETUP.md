# 설치 가이드 (Mac / Windows)

새 컴퓨터에 이 프로젝트를 처음 설치할 때 따라가는 문서입니다. **Dify 안에 만들어지는 앱·지식베이스·API 키·모델 자격증명은 Dify 자체의 내부 DB 데이터라서, 설치본 사이에 복사해 옮길 수 없습니다** — 매 설치마다 새로 만들어야 하고, 이 문서의 3단계(`setup_dify.py`)가 그 과정을 자동화합니다.

각 단계는 두 OS에 **공통으로 적용되는 내용**을 먼저 설명하고, 실행 명령만 다른 경우에 한해 **Mac/Linux**와 **Windows** 탭으로 나눕니다. 셸 명령 자체가 다른 게 아니라면(예: `docker compose up -d`) 한 번만 적습니다.

> `setup_dify.py`를 직접 고치거나 새 Dify 앱(에이전트)을 추가해야 한다면, 이 문서가 아니라 [term-standardization-mcp/AUTOMATION.md](term-standardization-mcp/AUTOMATION.md)를 보세요. 이 문서는 "설치 방법"만 다룹니다.

## 사전 준비 (공통)

- Docker Desktop 설치 및 실행 (최초 1회 실행해서 데몬을 띄워둘 것)
- Python 3.11+ 설치
- Git

## 0. 폴더 구조 (공통)

이 저장소와 Dify를 **형제 폴더**로 둡니다. `poc-start.*`/`start.*` 스크립트들이 상대 경로(`../dify/docker`)로 Dify를 찾기 때문에 이 구조가 강제됩니다.

```
projects/
  term-standardization/   <- 이 저장소
  dify/                    <- 1단계에서 새로 클론
```

## 1. Dify 새로 설치

**공통 — 공식 저장소가 아니라 우리 포크(`liswoo/dify`)를 클론합니다**

```bash
cd projects
git clone https://github.com/liswoo/dify.git
```

공식 `langgenius/dify` 대신 이 포크를 쓰는 이유 두 가지:

1. **버전 고정.** 공식 저장소를 그냥 `git clone`하면 그 시점의 최신 `main`이 딸려오는데, `setup_dify.py`/`dify_admin.py`는 Dify의 *내부* 서비스 API를 직접 호출하기 때문에([term-standardization-mcp/AUTOMATION.md](term-standardization-mcp/AUTOMATION.md) 참고) Dify 버전이 달라지면 조용히 깨질 수 있습니다. 포크는 만든 시점 스냅샷이라 우리가 실제로 검증한 커밋(`0df092d3c7`, 이미지 태그 `1.17.0`)에 고정되어 있고, 우리가 직접 "Sync fork"를 누르지 않는 한 계속 그 상태로 남습니다.
2. **커스텀 여지.** Dify 자체를 나중에 패치해야 할 일이 생기면 이 포크에 커밋하면 됩니다.

로컬 클론에는 원본 저장소도 `upstream`이라는 이름으로 같이 등록해두면, 나중에 의도적으로 업그레이드하고 싶을 때 편합니다 (기본 동작에는 필요 없음):

```bash
cd dify
git remote add upstream https://github.com/langgenius/dify.git
```

`dify/docker/.env.example`을 복사해 `.env`를 만들고, 아래 두 값을 설정합니다 (키 이름은 그대로, `.env` 파일 안에서 텍스트 편집기로 고치면 됩니다).

```env
SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=host.docker.internal
ENABLE_COLLABORATION_MODE=false
```

`COMPOSE_PROFILES` 값에서 `collaboration`을 제거합니다 (실시간 협업 오버레이가 멈춰서 UI가 안 먹는 버그 회피). 예:

```env
COMPOSE_PROFILES=${VECTOR_STORE:-weaviate},${DB_TYPE:-postgresql}
```

**Mac/Linux**
```bash
cd dify/docker
cp .env.example .env
```

**Windows (PowerShell)**
```powershell
cd dify\docker
Copy-Item .env.example .env
```

**공통 — 이제 두 OS 모두 동일**
```bash
docker compose up -d
```

몇 분 뒤 `http://localhost` 접속해서 **최초 관리자 계정을 만듭니다.** 이메일/비밀번호를 입력하는 단계라 자동화 대상이 아니며, 항상 사람이 직접 해야 합니다.

## 2. MCP 서버 설정

**공통**

`term-standardization-mcp/.env.example`을 복사해 `.env`를 만들고, `TERM_DB_PASSWORD`와 `DATABASE_URL`의 비밀번호 부분을 임의의 문자열로 채우고(같은 값이어야 함), `OPENAI_API_KEY`에 실제 OpenAI API 키를 넣습니다 — 3단계의 `setup_dify.py`가 이 값을 그대로 읽어 Dify 쪽 모델 공급자에도 등록합니다.

**Mac/Linux**
```bash
cd term-standardization-mcp
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
> `kiwipiepy` 설치 중 컴파일 오류가 나면 `xcode-select --install`로 Command Line Tools를 먼저 설치하세요.

```bash
chmod +x start.sh
./start.sh
```

**Windows (PowerShell)**
```powershell
cd term-standardization-mcp
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt
```
> `kiwipiepy` 설치 중 컴파일 오류가 나면 [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)(C++ 빌드 도구)를 먼저 설치하세요.

```powershell
.\start.ps1
```

**공통** — 두 경우 모두 `MCP ready: http://host.docker.internal:8100/mcp`가 뜨면 성공입니다.

## 3. Dify 설정 자동화 (`setup_dify.py`)

**완전히 공통입니다.** 파이썬 스크립트가 `docker exec`로 Dify 컨테이너 내부 서비스를 직접 호출하는 방식이라 OS에 따라 달라지는 부분이 없습니다 (venv 안의 파이썬 실행 파일 경로만 다릅니다).

```bash
# Mac/Linux
.venv/bin/python setup_dify.py
```
```powershell
# Windows
.venv\Scripts\python.exe setup_dify.py
```

전제 조건: 1단계에서 Dify 관리자 계정을 이미 만들었고, 2단계의 MCP 서버가 떠 있어야 합니다. 이 스크립트가 하는 일:

1. MCP 서버(`http://host.docker.internal:8100/mcp`)를 Dify에 등록 (이미 등록돼 있으면 도구 목록만 새로고침)
2. `.env`의 `OPENAI_API_KEY`를 Dify 모델 공급자에 등록 (이미 설정돼 있으면 건드리지 않음)
3. `data/scenario_catalog.json`의 "[가상]" 시나리오 문서를 지식베이스로 업로드 (이미 있는 문서는 건너뜀)
4. Chatflow(`용어표준화-대화형`) 빌드 → 임포트 → 배포
5. 목록조회 Workflow(`용어표준화-목록조회`) 빌드 → 임포트 → 배포
6. 두 앱의 발급 키를 `term-standardization-ui/app.js`의 `DIFY_CHAT_KEY`/`LIST_TERMS_KEY`에 자동 반영

**재실행해도 안전합니다.** 이미 있는 MCP 서버·OpenAI 키·지식베이스 문서·앱은 새로 만들지 않고 갱신만 하므로, 설정을 바꾸고 다시 돌리거나 실수로 두 번 실행해도 중복이 생기지 않습니다. Dify Studio 화면을 직접 조작하는 과정은 이제 없습니다.

## 4. Caddy · cloudflared 설치

프론트엔드(`:8090`)와 외부 공개 터널에 씁니다.

**Mac**
```bash
brew install caddy cloudflared
```

**Windows**
[caddyserver.com/download](https://caddyserver.com/download)와 [cloudflared 릴리스 페이지](https://github.com/cloudflare/cloudflared/releases)에서 `caddy.exe`, `cloudflared.exe`를 받아 이 저장소의 `tools/` 폴더에 둡니다 (`tools/Caddyfile`은 이미 있음 — 경로가 하드코딩돼 있지 않고 `poc-start.ps1`이 넘겨주는 `UI_DIR` 환경변수를 읽습니다).

## 5. 실행

**Mac/Linux**
```bash
cd term-standardization
chmod +x poc-start.sh poc-stop.sh
./poc-start.sh            # 로컬만: http://localhost:8090
./poc-start.sh --public   # 외부 공개 URL까지 발급
./poc-stop.sh             # 전체 종료 (데이터 보존)
```

**Windows (PowerShell)**
```powershell
cd term-standardization
.\poc-start.ps1            # 로컬만: http://localhost:8090
.\poc-start.ps1 -Public    # 외부 공개 URL까지 발급
.\poc-stop.ps1             # 전체 종료 (데이터 보존)
```

## 참고: DB 데이터는 새로 시작합니다

실제로 등록된 용어 데이터는 설치본 간에 이전하지 않습니다. `start.sh`/`start.ps1`이 `manage.py init-db`로 스키마만 만들고, 도메인 코드(수N7 등)와 카탈로그는 비어 있는 상태로 시작합니다. 데모용 시나리오 데이터가 필요하면:

```bash
.venv/bin/python manage.py import-catalog data/scenario_catalog.json
```
