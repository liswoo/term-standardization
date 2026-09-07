"""Reuse this workflow's existing OpenAI credential, protected with Windows DPAPI.
No credential is printed or written in plaintext. Run again after key rotation.
"""
import json
import subprocess
from pathlib import Path
import win32crypt

SCRIPT = '''
import json
from app_factory import create_app
from extensions.ext_database import db
from sqlalchemy import text
from core.helper.encrypter import decrypt_token
app=create_app()
if isinstance(app,tuple):
    app=app[1]
with app.app_context():
    row=db.session.execute(text("""SELECT c.tenant_id,c.encrypted_config FROM provider_credentials c
        JOIN providers p ON p.credential_id=c.id
        WHERE c.tenant_id=(SELECT tenant_id FROM apps WHERE id=:app_id)
        AND c.provider_name='langgenius/openai/openai' AND p.is_valid=true"""),
        {"app_id":"e27b2a07-0091-44ba-9b19-2ef1b1a871ed"}).mappings().one()
    config=json.loads(row["encrypted_config"])
    key=decrypt_token(row["tenant_id"],config["openai_api_key"])
    print("CREDENTIAL_PAYLOAD="+json.dumps({"key":key}))
'''

if __name__=="__main__":
    result=subprocess.run(["docker","exec","-i","docker-api-1","uv","run","--no-sync","--project","/app/api","python","-"],
        input=SCRIPT,text=True,encoding="utf-8",capture_output=True,timeout=60)
    lines=[line for line in result.stdout.splitlines() if line.startswith("CREDENTIAL_PAYLOAD=")]
    if result.returncode or len(lines)!=1:
        raise SystemExit("Dify credential linking failed. Secret output suppressed.")
    key=json.loads(lines[0].split("=",1)[1])["key"]
    if not key.startswith("sk-"):
        raise SystemExit("Unexpected credential format.")
    path=Path(__file__).parent/".runtime/model-credential.dpapi"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(win32crypt.CryptProtectData(key.encode(),"Term definition comparison",None,None,None,0))
    print("OpenAI credential linked with current-user Windows DPAPI protection.")
