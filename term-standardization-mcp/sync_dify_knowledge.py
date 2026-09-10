"""Create a separate Dify knowledge dataset from the same clearly synthetic catalog,
plus standard_guide.md so help/show_candidates questions ("정의는 어떻게 쓰면 돼?" etc.)
can retrieve the actual guide text. This dataset is display-only reference material for
the chatflow (see render_context's next_action-gated `reference` variable) - it never
gates registration; that's guideline_chunks/check_guideline's job (term_service/guideline.py),
a completely separate pgvector-backed RAG path.
Uses Dify document services and asynchronous index jobs. Never modifies existing datasets.
"""
import json
import re
from pathlib import Path
from dify_admin import execute

ROOT=Path(__file__).parent
catalog=json.loads((ROOT/"data/scenario_catalog.json").read_text(encoding="utf-8"))
guide_text=(ROOT/"data/standard_guide.md").read_text(encoding="utf-8")
guide_sections=[]
parts=re.split(r"(?m)^##\s+",guide_text)
if parts[0].strip():
    guide_sections.append(("0. 개요",parts[0].strip()))
for part in parts[1:]:
    title,_,rest=part.partition("\n")
    guide_sections.append((title.strip(),rest.strip()))
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
        description='시나리오 검증용 가상 데이터. 실제 공공기관 표준이 아님. 원본: scenario_catalog.json + standard_guide.md. 승인 대기 요청은 포함하지 않음.',
        indexing_technique='high_quality',account=account,permission='all_team_members',
        embedding_model_provider='langgenius/openai/openai',embedding_model_name='text-embedding-3-small',
        retrieval_model=RetrievalModel(search_method='semantic_search',reranking_enable=False,top_k=5,score_threshold_enabled=False),
        session=session)
def upsert(title,content):
    document=session.scalar(select(Document).where(Document.dataset_id==dataset.id,Document.name==title))
    if document:
        return {'name':title,'document_id':document.id,'status':document.indexing_status}
    payload={'name':title,'text':content,'indexing_technique':'high_quality','doc_language':'Korean',
        'process_rule':{'mode':'automatic'}}
    with app.test_request_context('/v1/datasets/'+dataset.id+'/document/create-by-text',method='POST',json=payload):
        g._login_user=account
        document,batch=_create_document_by_text(session=session,tenant_id=tenant_id,dataset_id=UUID(dataset.id))
        return {'name':title,'document_id':document.id,'batch':batch}
docs=[]
for row in CATALOG['terms']:
    title='[가상] '+row['name']
    abbr_line='영문약어: '+row['english_abbr'] if row.get('english_abbr') else ''
    content='\\n'.join(x for x in ['출처: 시나리오용 가상 데이터(공식 표준 아님)','표준명: '+row['name'],
        '정의: '+row['definition'],'도메인: '+row['domain'],abbr_line,
        '동의어: '+', '.join(row.get('synonyms',[]))] if x)
    docs.append(upsert(title,content))
for section,content in GUIDE_SECTIONS:
    docs.append(upsert('[가이드] '+section,content))
session.commit()
print('RESULT='+json.dumps({'dataset_id':dataset.id,'name':name,'documents':docs},ensure_ascii=False))
"""
if __name__=="__main__":
    result=execute("CATALOG="+repr(catalog)+"\nGUIDE_SECTIONS="+repr(guide_sections)+"\n"+body)
    (ROOT/".runtime/dify-knowledge.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
