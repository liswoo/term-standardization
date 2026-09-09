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
import re
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

def patch_app_js(chat_key,list_terms_key):
    app_js=ROOT.parent/"term-standardization-ui"/"app.js"
    text=app_js.read_text(encoding="utf-8")
    text,n1=re.subn(r'const DIFY_CHAT_KEY = "[^"]*";',f'const DIFY_CHAT_KEY = "{chat_key}";',text)
    text,n2=re.subn(r'const LIST_TERMS_KEY = "[^"]*";',f'const LIST_TERMS_KEY = "{list_terms_key}";',text)
    if n1!=1 or n2!=1:
        raise RuntimeError(f"Expected exactly one DIFY_CHAT_KEY/LIST_TERMS_KEY declaration in {app_js}, found {n1}/{n2}")
    app_js.write_text(text,encoding="utf-8")
    return app_js

def main():
    print("[1/6] MCP 서버 등록...",flush=True)
    print(run("dify_admin.py","mcp-register",capture=True).stdout.strip(),flush=True)

    print("[2/6] OpenAI 자격증명 등록...",flush=True)
    print(run("dify_admin.py","openai-credential",capture=True).stdout.strip(),flush=True)

    print("[3/6] 지식베이스 동기화...",flush=True)
    run("sync_dify_knowledge.py")

    print("[4/6] Chatflow 빌드·임포트·배포...",flush=True)
    run("build_chatflow.py")
    run("dify_admin.py","import","dify-chatflow.yaml")
    chatflow=last_json_line(run("scripts/publish_chatflow.py",capture=True).stdout)

    print("[5/6] 목록조회 Workflow 빌드·임포트·배포...",flush=True)
    list_terms=last_json_line(run("scripts/publish_list_terms_workflow.py",capture=True).stdout)

    print("[6/6] 프론트엔드 API 키 반영...",flush=True)
    app_js=patch_app_js(chatflow["key"],list_terms["key"])

    print()
    print("설치 완료.",flush=True)
    print(f"  Chatflow app_id: {chatflow['app_id']}",flush=True)
    print(f"  목록조회 app_id: {list_terms['app_id']}",flush=True)
    print(f"  app.js 갱신됨:   {app_js}",flush=True)

if __name__=="__main__":
    main()
