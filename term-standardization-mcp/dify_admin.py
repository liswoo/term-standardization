"""Dify administration through its own application services (no raw workflow DB writes)."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).parent

# No app_id is hardcoded here on purpose. A fresh Dify instance has exactly one
# tenant, created together with the first (owner) admin account at setup time,
# so that owner join is the only handle we need to act as "the workspace".
# This makes every action below independent of any particular app existing,
# which used to require a manually-built scaffold app just to get a tenant_id.
PRELUDE="""
import json
from app_factory import create_app
from extensions.ext_database import db
from sqlalchemy import select
from models.account import Account, TenantAccountJoin, TenantAccountRole
from models.model import App
from services.app_dsl_service import AppDslService
app=create_app()[1]
with app.app_context():
    session=db.session()
    join=session.scalar(select(TenantAccountJoin).where(TenantAccountJoin.role==TenantAccountRole.OWNER)
        .order_by(TenantAccountJoin.created_at))
    if join is None:
        raise SystemExit("No Dify tenant/owner account found - create the admin account at http://localhost first.")
    tenant_id=join.tenant_id
    account=session.get(Account,join.account_id)
    account.set_tenant_id_with_session(tenant_id,session=session)
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

def _read_env(path):
    values={}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line=line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key,_,value=line.partition("=")
            values[key.strip()]=value.strip()
    return values

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["import","mcp-register","openai-credential"])
    parser.add_argument("file",nargs="?")
    args=parser.parse_args()

    if args.action=="import":
        import yaml as _yaml
        content=Path(args.file).read_text(encoding="utf-8")
        app_name=_yaml.safe_load(content)["app"]["name"]
        saved=ROOT/f".runtime/{Path(args.file).stem}-import.json"
        existing=json.loads(saved.read_text(encoding="utf-8"))["app_id"] if saved.exists() else None
        # Fall back to looking the app up by name so a lost/renamed cache file
        # (or a fresh checkout on another machine that already ran setup once)
        # still updates the same app in place instead of creating a duplicate.
        result=execute(
            "existing="+repr(existing)+"\n"
            "if existing is None:\n"
            "    found=session.scalar(select(App).where(App.tenant_id==tenant_id,App.name=="+repr(app_name)+"))\n"
            "    existing=found.id if found else None\n"
            "result=AppDslService(session).import_app(account=account,import_mode='yaml-content',"
            "yaml_content="+repr(content)+",app_id=existing)\n"
            "session.commit()\nprint('RESULT='+result.model_dump_json())")
        saved.parent.mkdir(exist_ok=True)
        saved.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False))

    elif args.action=="mcp-register":
        from dify_mcp_config import MCP_SERVER_IDENTIFIER, MCP_ICON_EMOJI, MCP_ICON_BACKGROUND, mcp_server_url
        env=_read_env(ROOT/".env")
        server_url=mcp_server_url(env.get("MCP_PORT","8100"))
        result=execute(f"""
from sqlalchemy import select as _select
from models.tools import MCPToolProvider
from services.tools.mcp_tools_manage_service import MCPToolManageService
from core.entities.mcp_provider import MCPConfiguration
service=MCPToolManageService(session=session)
existing=session.scalar(_select(MCPToolProvider).where(MCPToolProvider.tenant_id==tenant_id,
    MCPToolProvider.server_identifier=={MCP_SERVER_IDENTIFIER!r}))
if existing is None:
    created=service.create_provider(tenant_id=tenant_id,user_id=account.id,server_url={server_url!r},
        name={MCP_SERVER_IDENTIFIER!r},icon={MCP_ICON_EMOJI!r},icon_type='emoji',icon_background={MCP_ICON_BACKGROUND!r},
        server_identifier={MCP_SERVER_IDENTIFIER!r},configuration=MCPConfiguration())
    reconnect=MCPToolManageService.reconnect_with_url(server_url={server_url!r},headers={{}},timeout=30,sse_read_timeout=300)
    db_provider=service.get_provider(provider_id=created.id,tenant_id=tenant_id)
    db_provider.authed=reconnect.authed
    db_provider.tools=reconnect.tools
    session.commit()
    tool_count=len(json.loads(db_provider.tools))
    status='created'
else:
    tools_result=service.list_provider_tools(tenant_id=tenant_id,provider_id=existing.id)
    session.commit()
    tool_count=len(tools_result.tools)
    status='refreshed'
print('RESULT='+json.dumps({{'status':status,'tool_count':tool_count,'server_url':{server_url!r}}}))
""")
        print(json.dumps(result,ensure_ascii=False))

    elif args.action=="openai-credential":
        env=_read_env(ROOT/".env")
        key=env.get("OPENAI_API_KEY","")
        if not key:
            raise SystemExit("OPENAI_API_KEY is empty in .env - set it before running this action.")
        result=execute(f"""
from services.model_provider_service import ModelProviderService
mps=ModelProviderService()
existing=mps.get_provider_credential(tenant_id=tenant_id,provider='langgenius/openai/openai')
if existing:
    status='already_configured'
else:
    mps.create_provider_credential(tenant_id=tenant_id,provider='langgenius/openai/openai',
        credentials={{'openai_api_key':{key!r}}},credential_name=None)
    status='created'
print('RESULT='+json.dumps({{'status':status}}))
""")
        print(json.dumps(result,ensure_ascii=False))
