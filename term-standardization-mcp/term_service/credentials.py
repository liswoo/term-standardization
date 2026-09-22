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

# Dify app API keys (2026-09-22) - previously hardcoded straight into app.js and
# shipped to every browser (a real, live secret anyone loading the page - not just
# anyone with repo access - could read via devtools; see admin_api.py's chat/
# list-terms proxies, the actual fix). scripts/publish_chatflow.py already wrote
# chatflow-key.txt on every deploy; list-terms-key.txt is new here, written the
# same way by scripts/publish_list_terms_workflow.py so re-publishing keeps both
# in sync without ever needing to hand either key to the frontend again.
def dify_chat_key():
    path=ROOT/".runtime/chatflow-key.txt"
    return path.read_text(encoding="utf-8").strip() if path.exists() else None

def dify_list_terms_key():
    path=ROOT/".runtime/list-terms-key.txt"
    return path.read_text(encoding="utf-8").strip() if path.exists() else None

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
        # A single local generation can sit right at the edge of OpenAI's usual
        # 35s - measured up to ~70s wall time once a timeout triggers max_retries=1
        # to redo the whole call from scratch. A local GPU has none of a hosted
        # API's request-level parallelism/headroom, so give it more room before
        # giving up rather than burning double the time on a wasted retry.
        kwargs.setdefault("timeout", 90)
        return OpenAI(api_key="local", base_url=LOCAL_LLM_BASE_URL, **kwargs)
    kwargs.setdefault("timeout", 35)
    return OpenAI(api_key=api_key(), base_url=None, **kwargs)

def llm_extra_params():
    """Provider-specific completion kwargs with no equivalent in OpenAI's own API
    surface, merged into a chat.completions.parse(...) call via **.
    Currently just Qwen3's thinking-mode switch: measured ~2x wall time per call
    without this, even though response_format's JSON-schema grammar already keeps
    the <think>...</think> trace out of the parsed result - the reasoning pass still
    runs and costs real time before the constrained-decoding answer starts. Same
    fix as build_chatflow.py's identical think=False for the Dify chatflow nodes."""
    if active_provider() == "local":
        return {"extra_body": {"think": False}}
    return {}
