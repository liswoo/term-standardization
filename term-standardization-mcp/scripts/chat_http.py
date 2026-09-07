"""Exercise the published Chatflow through its real HTTP API, without displaying credentials."""
import argparse
import json
from pathlib import Path
import urllib.request
import win32crypt
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('query')
parser.add_argument('--conversation-id',default='')
args=parser.parse_args()
key=win32crypt.CryptUnprotectData((ROOT/'.runtime/chatflow-key.dpapi').read_bytes(),None,None,None,0)[1].decode()
body={'query':args.query,'inputs':{},'user':'scenario-integration-test','response_mode':'blocking'}
if args.conversation_id:
    body['conversation_id']=args.conversation_id
request=urllib.request.Request('http://localhost/v1/chat-messages',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=120) as response:
    result=json.load(response)
(ROOT/'.runtime/last-dify-turn.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:result.get(k) for k in ['conversation_id','answer','metadata']},ensure_ascii=False))
