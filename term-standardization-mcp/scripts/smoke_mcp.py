"""Read-only MCP wire test, including structured tool results."""
import json
import urllib.request

url="http://host.docker.internal:8100/mcp"
headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream"}
counter=0
def call(method,params=None,notification=False):
    global counter
    counter+=1
    payload={"jsonrpc":"2.0","method":method,"params":params or {}}
    if not notification:
        payload["id"]=counter
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers=headers)
    with urllib.request.urlopen(req,timeout=30) as response:
        if response.headers.get("Mcp-Session-Id"):
            headers["Mcp-Session-Id"]=response.headers["Mcp-Session-Id"]
        raw=response.read().decode()
    if not raw:
        return None
    return json.loads(next((line[6:] for line in raw.splitlines() if line.startswith("data: ")),raw))

call("initialize",{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"dify-smoke","version":"1"}})
headers["MCP-Protocol-Version"]="2025-03-26"
call("notifications/initialized",notification=True)
tools=call("tools/list")["result"]["tools"]
print("Tool count:",len(tools))
for name,args in [("terminology_health",{}),("validate_term_name",{"term":"BMI"}),("search_standard_terms",{"term":"일일권장칼로리"}),("get_conversation_state",{"conversation_id":"smoke-read-only","requester":"test"})]:
    result=call("tools/call",{"name":name,"arguments":args})
    assert "error" not in result and not result["result"].get("isError"), result
    print(name,json.dumps(result["result"],ensure_ascii=False))
