"""Publish the scenario Chatflow using Dify services and provision a locally protected test key."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dify_admin import execute
app_id=json.loads((ROOT/'.runtime/dify-chatflow-import.json').read_text(encoding='utf-8'))['app_id']
result=execute("APP_ID="+repr(app_id)+"\n"+"""
from services.workflow_service import WorkflowService
from models.model import ApiToken
chat=session.get(App,APP_ID)
workflow=WorkflowService().publish_workflow(session=session,app_model=chat,account=account,marked_name='Scenario MCP integration')
chat.workflow_id=workflow.id
chat.updated_by=account.id
token=session.scalar(select(ApiToken).where(ApiToken.app_id==chat.id,ApiToken.type=='app'))
if token is None:
    token=ApiToken(app_id=chat.id,tenant_id=chat.tenant_id,type='app',token=ApiToken.generate_api_key('app-',24,session=session))
    session.add(token)
session.commit()
print('RESULT='+json.dumps({'app_id':chat.id,'key':token.token,'workflow_id':workflow.id}))
""")
key=result.pop('key')
(ROOT/'.runtime/chatflow-key.txt').write_text(key,encoding='utf-8')
result['key']=key
print(json.dumps(result))
