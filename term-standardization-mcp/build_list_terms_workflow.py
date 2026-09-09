"""Build an importable, read-only Dify Workflow that exposes list_terms to the frontend.

Kept separate from the conversational Chatflow: a dashboard read has no user
intent to classify and no conversation state, so it doesn't belong behind the
LLM-classification pipeline. This app is a single MCP tool call, callable via
a plain /v1/workflows/run POST with no inputs.
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
    data.update(tool_name=name,tool_label=name,tool_description=desc or name,tool_node_version="2",
        tool_configurations={},tool_parameters={k:{"type":"constant","value":v} for k,v in params.items()},
        is_team_authorization=True,paramSchemas=[],params={})
    return node(ident,name,"tool",data)

node("start","시작","start",{"variables":[]})
tool("list_terms","list_terms",{"limit":100},"실제 표준용어 카탈로그와 검토 대기 등록 요청 목록을 조회한다.")
node("end","출력","end",{"outputs":[{"variable":"terms","value_selector":["list_terms","json"],"value_type":"array[object]"}]})

edges=[]
for left,right in zip(nodes,nodes[1:]):
    edges.append({"id":left["id"]+"-"+right["id"],"type":"custom","source":left["id"],"target":right["id"],
        "sourceHandle":"source","targetHandle":"target","data":{"sourceType":left["data"]["type"],"targetType":right["data"]["type"]}})

doc=copy.deepcopy(original)
doc["app"].update(name="용어표준화-목록조회",mode="workflow",
    description="프론트엔드 대시보드용 읽기 전용 워크플로우. 실제 표준용어 카탈로그와 검토 대기 등록 요청 목록을 반환한다.")
doc["workflow"]["graph"]={"nodes":nodes,"edges":edges,"viewport":{"x":0,"y":0,"zoom":0.7}}
doc["workflow"]["conversation_variables"]=[]
(ROOT/"dify-list-terms-workflow.yaml").write_text(yaml.safe_dump(doc,allow_unicode=True,sort_keys=False),encoding="utf-8")
print("Created dify-list-terms-workflow.yaml")
