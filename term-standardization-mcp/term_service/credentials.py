import json
import os
from .config import ROOT, OPENAI_MODEL, LOCAL_LLM_MODEL, LOCAL_LLM_BASE_URL, LLM_PROVIDER_DEFAULT

PROVIDER_OVERRIDE_FILE = ROOT / ".runtime/llm_provider.json"

def api_key():
    value=os.getenv("OPENAI_API_KEY")
    if value:
        return value
    path=ROOT/".runtime/model-credential.dpapi"
    if path.exists():
        import win32crypt
        return win32crypt.CryptUnprotectData(path.read_bytes(),None,None,None,0)[1].decode()
    return None

def active_provider():
    """"openai" or "local". Read fresh every call (not cached at import) so the
    Settings-screen switch (set_active_provider) takes effect on the very next
    request, without restarting this server."""
    if PROVIDER_OVERRIDE_FILE.exists():
        try:
            value = json.loads(PROVIDER_OVERRIDE_FILE.read_text(encoding="utf-8")).get("provider")
            if value in ("openai", "local"):
                return value
        except Exception:
            pass
    return LLM_PROVIDER_DEFAULT if LLM_PROVIDER_DEFAULT in ("openai", "local") else "openai"

def set_active_provider(provider):
    if provider not in ("openai", "local"):
        raise ValueError("provider must be 'openai' or 'local'")
    PROVIDER_OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROVIDER_OVERRIDE_FILE.write_text(json.dumps({"provider": provider}), encoding="utf-8")

def current_llm_model():
    return LOCAL_LLM_MODEL if active_provider() == "local" else OPENAI_MODEL

def llm_configured():
    # A local OpenAI-compatible server (Ollama etc.) doesn't require a real key -
    # only the hosted OpenAI path needs one.
    if active_provider() == "local":
        return bool(LOCAL_LLM_BASE_URL)
    return bool(api_key())

def llm_client(**kwargs):
    from openai import OpenAI
    if active_provider() == "local":
        return OpenAI(api_key="local", base_url=LOCAL_LLM_BASE_URL, **kwargs)
    return OpenAI(api_key=api_key(), base_url=None, **kwargs)
