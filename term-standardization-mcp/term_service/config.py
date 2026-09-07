import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
SEMANTIC_THRESHOLD = float(os.getenv("SEMANTIC_THRESHOLD", "0.85"))
CONFIDENCE_THRESHOLD = float(os.getenv("DEFINITION_CONFIDENCE_THRESHOLD", "0.85"))
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
