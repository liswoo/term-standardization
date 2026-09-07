"""Compatibility entry point: test the published Chatflow over HTTP."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name("chat_http.py")),run_name="__main__")
