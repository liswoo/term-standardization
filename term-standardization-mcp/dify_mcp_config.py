"""Shared MCP provider identity, used both to register the MCP server in Dify
(dify_admin.py mcp-register) and to construct the MCP tool nodes embedded in the
generated app DSL (build_chatflow.py, build_list_terms_workflow.py).

These values used to be scraped from a manually-built scaffold app (create an
empty Workflow app in Studio, add the MCP server, drag one tool node onto the
canvas, save, then export its DSL as backups/workflow-original.yaml). They are
plain strings we chose ourselves, not anything Dify generates, so there is
nothing to scrape: fixing them here removes that whole manual step.
"""
MCP_SERVER_IDENTIFIER = "term-standardization"
MCP_SERVER_NAME = "term-standardization"
MCP_ICON_EMOJI = "🔗"
MCP_ICON_BACKGROUND = "#6366F1"

# Fields copied verbatim onto every MCP "tool" node in a Dify workflow graph.
MCP_PROVIDER_FIELDS = {
    "provider_id": MCP_SERVER_IDENTIFIER,
    "provider_name": MCP_SERVER_IDENTIFIER,
    "provider_show_name": MCP_SERVER_IDENTIFIER,
    "provider_type": "mcp",
    "provider_icon": {"background": MCP_ICON_BACKGROUND, "content": MCP_ICON_EMOJI},
    "plugin_id": "",
    "plugin_unique_identifier": "",
}


def mcp_server_url(mcp_port: str | int = 8100) -> str:
    return f"http://host.docker.internal:{mcp_port}/mcp"
