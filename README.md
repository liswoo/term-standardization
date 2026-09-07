# 용어표준화 AI 에이전트

공공기관 데이터 표준 용어 등록을 대화형으로 처리하는 POC. Dify + MCP 서버(PostgreSQL/pgvector) + 정적 프론트엔드로 구성됩니다.

## 구조

- `term-standardization-mcp/` — MCP 서버(19개 도구), 검색·검증·등록 업무 로직, DB 스키마, Dify Chatflow/Workflow 빌드 스크립트
- `term-standardization-ui/` — 관리자 콘솔 + 채팅 패널 정적 프론트엔드
- `tools/Caddyfile` — 프론트엔드와 Dify API를 한 오리진(`:8090`)으로 묶는 리버스 프록시 설정
- `poc-start.ps1` / `poc-stop.ps1` — Windows용 통합 실행/종료
- `poc-start.sh` / `poc-stop.sh` — macOS/Linux용 통합 실행/종료

Dify 자체(`dify/`)는 이 저장소에 포함하지 않습니다. 공식 저장소를 별도로 클론해서 이 저장소와 형제 폴더로 둡니다.

## 처음 설정하는 경우

- **Windows**: 기존에 설정된 환경을 그대로 사용합니다.
- **다른 컴퓨터(예: Mac)로 처음 옮기는 경우**: [MAC_SETUP.md](MAC_SETUP.md)를 순서대로 따라하세요. Dify 안의 앱·지식베이스·API 키는 설치마다 새로 만들어야 합니다 — Windows에서 그대로 복사해 올 수 없습니다.

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
