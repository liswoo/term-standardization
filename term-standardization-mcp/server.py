"""Existing MCP entrypoint, run with .venv/Scripts/python.exe server.py."""
from term_service.tools import mcp
from term_service import admin_api  # noqa: F401 - registers the /admin/* HTTP routes on `mcp`
from run_server import main

if __name__ == '__main__':
    main()
