"""Create a separate Dify knowledge dataset from the same clearly synthetic catalog.
Uses Dify document services and asynchronous index jobs. Never modifies existing datasets.
"""
import json
from pathlib import Path
from dify_admin import execute

ROOT=Path(__file__).parent
catalog=json.loads((ROOT/"data/scenario_catalog.json").read_text(encoding="utf-8"))
body="""
from flask import g
from models.dataset import Dataset,Document
from services.dataset_service import DatasetService
from services.entities.knowledge_entities.knowledge_entities import RetrievalModel
from controllers.service_api.dataset.document import _create_document_by_text
from uuid import UUID
name='용어표준화-시나리오데이터(가상)'
dataset=session.scalar(select(Dataset).where(Dataset.tenant_id==tenant_id,Dataset.name==name))
if dataset is None:
    dataset=DatasetService.create_empty_dataset(tenant_id=tenant_id,name=name,
        description='시나리오 검증용 가상 데이터. 실제 공공기관 표준이 아님. 원본: scenario_catalog.json. 승인 대기 요청은 포함하지 않음.',
        indexing_technique='high_quality',account=account,permission='all_team_members',
        embedding_model_provider='langgenius/openai/openai',embedding_model_name='text-embedding-3-small',
        retrieval_model=RetrievalModel(search_method='semantic_search',reranking_enable=False,top_k=5,score_threshold_enabled=False),
        session=session)
docs=[]
for row in CATALOG['terms']:
    title='[가상] '+row['name']
    document=session.scalar(select(Document).where(Document.dataset_id==dataset.id,Document.name==title))
    if document:
        docs.append({'name':title,'document_id':document.id,'status':document.indexing_status})
        continue
    content='\\n'.join(['출처: 시나리오용 가상 데이터(공식 표준 아님)','표준명: '+row['name'],
        '정의: '+row['definition'],'도메인: '+row['domain'],'동의어: '+', '.join(row.get('synonyms',[]))])
    payload={'name':title,'text':content,'indexing_technique':'high_quality','doc_language':'Korean',
        'process_rule':{'mode':'automatic'}}
    with app.test_request_context('/v1/datasets/'+dataset.id+'/document/create-by-text',method='POST',json=payload):
        g._login_user=account
        document,batch=_create_document_by_text(session=session,tenant_id=tenant_id,dataset_id=UUID(dataset.id))
        docs.append({'name':title,'document_id':document.id,'batch':batch})
session.commit()
print('RESULT='+json.dumps({'dataset_id':dataset.id,'name':name,'documents':docs},ensure_ascii=False))
"""
if __name__=="__main__":
    result=execute("CATALOG="+repr(catalog)+"\n"+body)
    (ROOT/".runtime/dify-knowledge.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
