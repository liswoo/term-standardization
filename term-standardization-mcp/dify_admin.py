"""Dify administration through its own application services (no raw workflow DB writes)."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).parent
PRELUDE="""
import json
from app_factory import create_app
from extensions.ext_database import db
from sqlalchemy import select
from models.model import App
from models.account import Account
from services.app_dsl_service import AppDslService
app=create_app()[1]
with app.app_context():
    session=db.session()
    original=session.get(App,'e27b2a07-0091-44ba-9b19-2ef1b1a871ed')
"""

def execute(body):
    script=PRELUDE+"\n".join("    "+line for line in body.splitlines())+"\nimport sys,os\nsys.stdout.flush()\nos._exit(0)\n"
    result=subprocess.run(["docker","exec","-i","docker-api-1","uv","run","--no-sync","--project","/app/api","python","-"],
        input=script,text=True,encoding="utf-8",capture_output=True,timeout=150)
    if result.returncode:
        # Administrative code carries no passwords or decrypted keys.
        raise RuntimeError(result.stderr[-3500:])
    lines=[l[7:] for l in result.stdout.splitlines() if l.startswith("RESULT=")]
    if len(lines)!=1:
        raise RuntimeError("Missing Dify service result")
    return json.loads(lines[0])

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["backup","refresh","import"])
    parser.add_argument("file",nargs="?")
    args=parser.parse_args()
    if args.action=="backup":
        result=execute("dsl=AppDslService.export_dsl(original,session=session,include_secret=False)\nprint('RESULT='+json.dumps({'dsl':dsl}))")
        path=ROOT/"backups/workflow-original.yaml"
        if path.exists():
            raise SystemExit("Original backup already exists; not overwritten.")
        path.write_text(result["dsl"],encoding="utf-8")
        print("Original workflow DSL backed up.")
    elif args.action=="refresh":
        result=execute("""from models.tools import MCPToolProvider
from services.tools.mcp_tools_manage_service import MCPToolManageService
providers=session.scalars(select(MCPToolProvider).where(MCPToolProvider.tenant_id==original.tenant_id)).all()
out=[]
for provider in providers:
    entity=provider.to_entity()
    url=entity.decrypt_server_url()
    if 'host.docker.internal:8100' not in url:
        continue
    MCPToolManageService(session=session).list_provider_tools(tenant_id=original.tenant_id,provider_id=provider.id)
    out.append({'id':provider.id,'name':provider.name,'tool_count':len(json.loads(provider.tools))})
session.commit()
print('RESULT='+json.dumps(out))""")
        print(json.dumps(result,ensure_ascii=False))
    else:
        content=Path(args.file).read_text(encoding="utf-8")
        saved=ROOT/".runtime/chatflow-import.json"
        existing=json.loads(saved.read_text(encoding="utf-8"))["app_id"] if saved.exists() else None
        result=execute("account=session.get(Account,original.created_by)\naccount.set_tenant_id_with_session(original.tenant_id,session=session)\n"+
            "result=AppDslService(session).import_app(account=account,import_mode='yaml-content',yaml_content="+repr(content)+",app_id="+repr(existing)+")\n"+
            "session.commit()\nprint('RESULT='+result.model_dump_json())")
        (ROOT/".runtime/chatflow-import.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False))
