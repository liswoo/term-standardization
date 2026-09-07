"""Build, import and publish the read-only list_terms Dify Workflow, and provision a
plaintext frontend API key (this app returns no sensitive data, so unlike the chatflow's
test key there's no reason to DPAPI-protect it; it's meant to be embedded in app.js).
Re-running this script updates the existing app in place (tracked by app_id).
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dify_admin import execute

subprocess.run([sys.executable,str(ROOT/"build_list_terms_workflow.py")],check=True,cwd=ROOT)
content=(ROOT/"dify-list-terms-workflow.yaml").read_text(encoding="utf-8")

tracking=ROOT/".runtime/list-terms-import.json"
existing=json.loads(tracking.read_text(encoding="utf-8"))["app_id"] if tracking.exists() else None

import_result=execute(
    "account=session.get(Account,original.created_by)\n"
    "account.set_tenant_id_with_session(original.tenant_id,session=session)\n"
    "from services.app_dsl_service import AppDslService\n"
    "result=AppDslService(session).import_app(account=account,import_mode='yaml-content',yaml_content="+repr(content)+",app_id="+repr(existing)+")\n"
    "session.commit()\n"
    "print('RESULT='+result.model_dump_json())"
)
tracking.write_text(json.dumps(import_result,ensure_ascii=False,indent=2),encoding="utf-8")

publish_result=execute("APP_ID="+repr(import_result["app_id"])+"\n"+"""
from services.workflow_service import WorkflowService
from models.model import ApiToken
account=session.get(Account,original.created_by)
account.set_tenant_id_with_session(original.tenant_id,session=session)
app=session.get(App,APP_ID)
workflow=WorkflowService().publish_workflow(session=session,app_model=app,account=account,marked_name='List terms read API')
app.workflow_id=workflow.id
app.updated_by=account.id
token=session.scalar(select(ApiToken).where(ApiToken.app_id==app.id,ApiToken.type=='app'))
if token is None:
    token=ApiToken(app_id=app.id,tenant_id=app.tenant_id,type='app',token=ApiToken.generate_api_key('app-',24,session=session))
    session.add(token)
session.commit()
print('RESULT='+json.dumps({'app_id':app.id,'key':token.token,'workflow_id':workflow.id}))
""")
print(json.dumps(publish_result,ensure_ascii=False))
