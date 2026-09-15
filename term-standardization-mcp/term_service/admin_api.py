"""Local-only admin HTTP routes for the admin UI's Settings-screen LLM provider
switch. Plain REST endpoints on the same server.py process (port 8100),
proxied by Caddy at /admin/* so the browser can call them same-origin. No
auth, matching this PoC's existing no-auth posture (CLAUDE.md known issue #2)
- anyone who can reach this server can already reconfigure it via docker exec,
so this adds no new exposure.
"""
import asyncio
import subprocess
import sys
from pathlib import Path
from starlette.requests import Request
from starlette.responses import JSONResponse
from .tools import mcp
from .credentials import active_provider, set_active_provider, llm_configured

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable  # this same .venv's interpreter

def _redeploy_chatflow():
    """Rebuild/import/publish the Dify chatflow so its intent/reply nodes pick
    up whatever provider build_chatflow.py's active_provider() reads at import
    time. Mirrors CLAUDE.md's mandatory 3-step deploy - skipping a step would
    silently redeploy a stale draft (see CLAUDE.md's own warning about that)."""
    steps = (["build_chatflow.py"], ["dify_admin.py", "import", "dify-chatflow.yaml"],
        ["scripts/publish_chatflow.py"])
    for args in steps:
        result = subprocess.run([PYTHON, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"{args[0]} failed: {result.stderr[-2000:]}")

@mcp.custom_route("/admin/llm-status", methods=["GET"])
async def llm_status(request: Request) -> JSONResponse:
    return JSONResponse({"provider": active_provider(), "configured": llm_configured()})

@mcp.custom_route("/admin/llm-provider", methods=["POST"])
async def switch_llm_provider(request: Request) -> JSONResponse:
    body = await request.json()
    provider = body.get("provider")
    if provider not in ("openai", "local"):
        return JSONResponse({"ok": False, "error": "provider must be 'openai' or 'local'"}, status_code=400)
    set_active_provider(provider)
    try:
        # Rebuilding/publishing the Dify app is a docker exec + HTTP round trip
        # taking several seconds - run off the event loop so it doesn't block
        # other requests to this server while it's in flight.
        await asyncio.to_thread(_redeploy_chatflow)
    except Exception as error:
        return JSONResponse({"ok": False, "provider": active_provider(), "error": str(error)}, status_code=502)
    return JSONResponse({"ok": True, "provider": active_provider(), "configured": llm_configured()})
