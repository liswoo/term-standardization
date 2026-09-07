import os
from .config import ROOT

def api_key():
    value=os.getenv("OPENAI_API_KEY")
    if value:
        return value
    path=ROOT/".runtime/model-credential.dpapi"
    if path.exists():
        import win32crypt
        return win32crypt.CryptUnprotectData(path.read_bytes(),None,None,None,0)[1].decode()
    return None
