"""One-shot Dify setup for this project. Replaces the manual Studio steps
(create an empty Workflow app, add the MCP server, drag a tool node onto the
canvas, save; paste the OpenAI key into the model provider screen) with a
single command.

Requires, in order:
  1. Dify running (docker compose up -d in ../dify/docker), with the admin
     account already created once at http://localhost. Creating that very
     first account needs a password, so it is the one step this script
     cannot do for you - see MAC_SETUP.md.
  2. This project's own MCP server already running (./start.sh).
  3. .env filled in (TERM_DB_PASSWORD, DATABASE_URL, OPENAI_API_KEY).

Then:
    .venv/bin/python setup_dify.py

Safe to re-run: every step below detects what already exists and reuses it
(same MCP provider, same OpenAI credential, same two apps - updated in place
rather than duplicated) instead of erroring or creating duplicates.
"""
import json
import sys
from pathlib import Path
import subprocess

ROOT=Path(__file__).parent
PY=sys.executable

def run(*args,capture=False):
    result=subprocess.run([PY,*args],cwd=ROOT,text=True,capture_output=capture)
    if capture:
        sys.stdout.write(result.stdout)
    if result.returncode:
        if capture:
            sys.stderr.write(result.stderr)
        raise SystemExit(f"{' '.join(args)} failed (exit {result.returncode})")
    return result

def last_json_line(text):
    for line in reversed(text.strip().splitlines()):
        line=line.strip()
        if line:
            return json.loads(line)
    raise RuntimeError("No output to parse")

def main():
    print("[1/5] MCP 서버 등록...",flush=True)
    print(run("dify_admin.py","mcp-register",capture=True).stdout.strip(),flush=True)

    print("[2/5] OpenAI 자격증명 등록...",flush=True)
    print(run("dify_admin.py","openai-credential",capture=True).stdout.strip(),flush=True)

    print("[3/5] 지식베이스 동기화...",flush=True)
    run("sync_dify_knowledge.py")

    print("[4/5] Chatflow 빌드·임포트·배포...",flush=True)
    run("build_chatflow.py")
    run("dify_admin.py","import","dify-chatflow.yaml")
    chatflow=last_json_line(run("scripts/publish_chatflow.py",capture=True).stdout)

    print("[5/5] 목록조회 Workflow 빌드·임포트·배포...",flush=True)
    list_terms=last_json_line(run("scripts/publish_list_terms_workflow.py",capture=True).stdout)

    print()
    print("설치 완료.",flush=True)
    print(f"  Chatflow app_id: {chatflow['app_id']}",flush=True)
    print(f"  목록조회 app_id: {list_terms['app_id']}",flush=True)
    print("  두 앱의 API 키는 admin_api.py의 /admin/chat, /admin/list-terms 프록시가",flush=True)
    print("  .runtime/chatflow-key.txt, .runtime/list-terms-key.txt에서 직접 읽습니다",flush=True)
    print("  (프론트엔드는 더 이상 키를 갖고 있지 않음 - CLAUDE.md 2026-09-22 절 참고).",flush=True)

if __name__=="__main__":
    main()
