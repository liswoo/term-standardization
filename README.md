# 용어표준화 AI 에이전트

공공기관 데이터 표준 용어 등록을 대화형으로 처리하는 POC. Dify + MCP 서버(PostgreSQL/pgvector) + 정적 프론트엔드로 구성됩니다.

> **새 세션(에이전트/사람 모두)은 먼저 [CLAUDE.md](CLAUDE.md)를 읽으세요.** 현재 아키텍처, 반복 발견된 엔지니어링 패턴, 미해결 이슈/다음 작업 후보를 정리해둔 문서입니다. 이 README는 저장소 구조와 실행 명령만 다룹니다.

## 구조

- `term-standardization-mcp/` — MCP 서버(22개 도구), 검색·검증·등록 업무 로직, DB 스키마, Dify Chatflow/Workflow 빌드 스크립트
- `term-standardization-ui/` — 관리자 콘솔 + 채팅 패널 정적 프론트엔드
- `tools/Caddyfile` — 프론트엔드와 Dify API를 한 오리진(`:8090`)으로 묶는 리버스 프록시 설정
- `poc-start.ps1` / `poc-stop.ps1` — Windows용 통합 실행/종료
- `poc-start.sh` / `poc-stop.sh` — macOS/Linux용 통합 실행/종료

Dify 자체(`dify/`)는 이 저장소에 포함하지 않습니다. 공식 저장소를 별도로 클론해서 이 저장소와 형제 폴더로 둡니다.

## 처음 설정하는 경우 (Mac / Windows)

[SETUP.md](SETUP.md)를 순서대로 따라하세요. Dify 안의 앱·지식베이스·API 키·모델 자격증명은 설치본마다 새로 만들어야 합니다(다른 컴퓨터에서 복사해 올 수 없음) — `term-standardization-mcp/setup_dify.py` 스크립트 하나가 Dify Studio를 손으로 클릭하는 과정 없이 이 전체 과정을 자동화합니다. 이 자동화 자체를 고치거나 새 에이전트를 추가하려면 [term-standardization-mcp/AUTOMATION.md](term-standardization-mcp/AUTOMATION.md)를 보세요.

## 실행

```bash
# 로컬에서만 확인
./poc-start.sh            # Windows: .\poc-start.ps1

# 외부 공개 URL까지 발급 (세미나 발표 등)
./poc-start.sh --public   # Windows: .\poc-start.ps1 -Public

# 전체 종료 (데이터는 보존)
./poc-stop.sh              # Windows: .\poc-stop.ps1
```

## 세미나 자료

아키텍처 설명, 발표 스크립트 등은 별도로 게시된 Claude 아티팩트를 참고하세요.
