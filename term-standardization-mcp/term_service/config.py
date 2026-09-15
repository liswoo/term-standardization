import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
SEMANTIC_THRESHOLD = float(os.getenv("SEMANTIC_THRESHOLD", "0.85"))
CONFIDENCE_THRESHOLD = float(os.getenv("DEFINITION_CONFIDENCE_THRESHOLD", "0.85"))

# Two LLM profiles co-exist so the Settings-screen switch (credentials.py's
# active_provider()) can flip between them at runtime without editing .env -
# unlike the old single LLM_MODEL/LLM_BASE_URL pair, both providers' settings
# stay loaded simultaneously.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen3-8b-q8")
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
# Which profile is active when no runtime override file exists yet (see
# credentials.active_provider()). "openai" or "local".
LLM_PROVIDER_DEFAULT = os.getenv("LLM_PROVIDER", "openai")

# TEST-ONLY QUALITY TRADEOFF - see registration.py's prepare() and CLAUDE.md's
# "로컬 모델(Ollama) 테스트" section before touching this. Caps how many
# candidate terms registration.prepare() runs compare() against when the
# active provider is "local" - never applied to OpenAI. Exists solely to keep
# local testing (one GPU, effectively serialized calls) inside Dify's 5-minute
# MCP tool timeout; it trades duplicate-detection coverage for speed and must
# not be treated as the intended production behavior.
LOCAL_COMPARE_CANDIDATE_CAP = int(os.getenv("LOCAL_COMPARE_CANDIDATE_CAP", "5"))
