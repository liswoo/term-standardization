"""Build an importable, read-only Dify Workflow that exposes list_terms/list_standard_words/
list_data_domains to the frontend admin console.

Kept separate from the conversational Chatflow: a dashboard read has no user
intent to classify and no conversation state, so it doesn't belong behind the
LLM-classification pipeline. Callable via a plain /v1/workflows/run POST with
`inputs: {limit, offset, q, status, domain, requester, words_limit, words_offset,
words_q, words_status, words_requester, words_is_format_word}` - the term catalog
and word dictionary each page/filter independently (separate views, separate
filter state), while domains has no inputs since it always returns the full
active list (126 rows - small enough to never need paging).

All new filter variables are plain "text-input" Dify variables, not "select"/
"checkbox" - Dify's own UI never renders these (the admin console's own <select>/
checkbox controls are what the user actually sees; this workflow is just a typed
pass-through API called by app.js), and a plain string lets "no filter" simply be
"" for every one of them, including is_format_word ("true"/"false"/"").
"""
import copy
from pathlib import Path
import yaml
from dify_mcp_config import MCP_PROVIDER_FIELDS as provider

ROOT=Path(__file__).parent
original=yaml.safe_load((ROOT/"templates/dify_app_base.yaml").read_text(encoding="utf-8"))

nodes=[]
def node(ident,title,kind,data):
    result={"id":ident,"type":"custom","data":{"title":title,"type":kind,"desc":"","version":"1",**data},
        "position":{"x":len(nodes)*340,"y":150},"width":260,"height":100,"sourcePosition":"right","targetPosition":"left"}
    nodes.append(result)
    return result

def tool(ident,name,params,desc=""):
    data={k:copy.deepcopy(provider[k]) for k in ["provider_id","provider_name","provider_show_name","provider_type","provider_icon","plugin_id","plugin_unique_identifier"] if k in provider}
    # "mixed" (not "constant") lets a param's value be a {{#start.var#}} reference
    # resolved from the start node's own input variables at run time - same
    # mechanism build_chatflow.py already uses for e.g. {{#sys.conversation_id#}}.
    data.update(tool_name=name,tool_label=name,tool_description=desc or name,tool_node_version="2",
        tool_configurations={},tool_parameters={k:{"type":"mixed","value":v} for k,v in params.items()},
        is_team_authorization=True,paramSchemas=[],params={})
    return node(ident,name,"tool",data)

node("start","시작","start",{"variables":[
    {"variable":"limit","label":"limit","type":"number","required":False},
    {"variable":"offset","label":"offset","type":"number","required":False},
    {"variable":"q","label":"q","type":"text-input","max_length":200,"required":False},
    {"variable":"status","label":"status","type":"text-input","max_length":20,"required":False},
    {"variable":"domain","label":"domain","type":"text-input","max_length":100,"required":False},
    {"variable":"requester","label":"requester","type":"text-input","max_length":200,"required":False},
    {"variable":"words_limit","label":"words_limit","type":"number","required":False},
    {"variable":"words_offset","label":"words_offset","type":"number","required":False},
    {"variable":"words_q","label":"words_q","type":"text-input","max_length":200,"required":False},
    {"variable":"words_status","label":"words_status","type":"text-input","max_length":20,"required":False},
    {"variable":"words_requester","label":"words_requester","type":"text-input","max_length":200,"required":False},
    {"variable":"words_is_format_word","label":"words_is_format_word","type":"text-input","max_length":10,"required":False},
]})
tool("list_terms","list_terms",{"limit":"{{#start.limit#}}","offset":"{{#start.offset#}}","q":"{{#start.q#}}",
    "status":"{{#start.status#}}","domain":"{{#start.domain#}}","requester":"{{#start.requester#}}"},
    "실제 표준용어 카탈로그와 검토 대기 등록 요청 목록을 페이지 단위로 조회한다.")
tool("list_standard_words","list_standard_words",
    {"limit":"{{#start.words_limit#}}","offset":"{{#start.words_offset#}}","q":"{{#start.words_q#}}",
     "status":"{{#start.words_status#}}","requester":"{{#start.words_requester#}}",
     "is_format_word":"{{#start.words_is_format_word#}}"},
    "표준단어(standard_words) 사전을 페이지 단위로 조회한다.")
tool("list_data_domains","list_data_domains",{},"실제 활성 표준도메인 전체 목록을 조회한다 (페이지네이션 없음).")
node("end","출력","end",{"outputs":[
    {"variable":"terms","value_selector":["list_terms","json"],"value_type":"array[object]"},
    {"variable":"words","value_selector":["list_standard_words","json"],"value_type":"array[object]"},
    {"variable":"domains","value_selector":["list_data_domains","json"],"value_type":"array[object]"},
]})

edges=[]
for left,right in zip(nodes,nodes[1:]):
    edges.append({"id":left["id"]+"-"+right["id"],"type":"custom","source":left["id"],"target":right["id"],
        "sourceHandle":"source","targetHandle":"target","data":{"sourceType":left["data"]["type"],"targetType":right["data"]["type"]}})

doc=copy.deepcopy(original)
doc["app"].update(name="용어표준화-목록조회",mode="workflow",
    description="프론트엔드 대시보드용 읽기 전용 워크플로우. 표준용어/표준단어 카탈로그(페이지네이션), 검토 대기 등록 요청, 표준도메인 전체 목록을 반환한다.")
doc["workflow"]["graph"]={"nodes":nodes,"edges":edges,"viewport":{"x":0,"y":0,"zoom":0.7}}
doc["workflow"]["conversation_variables"]=[]
(ROOT/"dify-list-terms-workflow.yaml").write_text(yaml.safe_dump(doc,allow_unicode=True,sort_keys=False),encoding="utf-8")
print("Created dify-list-terms-workflow.yaml")
