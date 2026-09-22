"""Revoke the chatflow's and list-terms workflow's existing Dify app API tokens and
provision fresh ones, then re-run both publish scripts so .runtime/chatflow-key.txt
and .runtime/list-terms-key.txt (and the live Dify apps) end up on the new values.

Use this whenever an old key may have leaked (e.g. it was committed to git at some
point - see CLAUDE.md's "Dify API 키를 프론트엔드에서 제거" section, 2026-09-22) or on
a fixed rotation schedule. Restart the MCP server after running this (./start.sh
--restart) so admin_api.py's chat/list-terms proxies pick up the new keys - they read
the .runtime/*.txt files at request time, not at import time, so a restart isn't
strictly required for correctness, but the two old key files are overwritten in
place and any request in flight against the old key will start failing the moment
this script deletes it from Dify's side, so redeploying close together minimizes
that window.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dify_admin import execute

chatflow_app_id = json.loads((ROOT / ".runtime/dify-chatflow-import.json").read_text(encoding="utf-8"))["app_id"]
list_terms_app_id = json.loads((ROOT / ".runtime/list-terms-import.json").read_text(encoding="utf-8"))["app_id"]

result = execute(
    "from models.model import ApiToken\n"
    "import json as _json\n"
    "deleted=session.query(ApiToken).filter(ApiToken.app_id.in_(["
    + repr(chatflow_app_id) + "," + repr(list_terms_app_id) + "]),ApiToken.type=='app').delete(synchronize_session=False)\n"
    "session.commit()\n"
    "print('RESULT='+_json.dumps({'deleted':deleted}))"
)
print(f"Revoked {result['deleted']} existing token(s). Re-publishing both apps to provision new ones...")

venv_python = ROOT / ".venv/bin/python"
subprocess.run([str(venv_python), str(ROOT / "scripts/publish_chatflow.py")], check=True, cwd=ROOT)
subprocess.run([str(venv_python), str(ROOT / "scripts/publish_list_terms_workflow.py")], check=True, cwd=ROOT)

print("Done. Run ./start.sh --restart (or start.ps1) to pick up the new keys.")
