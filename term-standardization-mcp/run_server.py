import os
from mcp.server.streamable_http import TransportSecuritySettings
from term_service.tools import mcp

def main():
    security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost:*","127.0.0.1:*","host.docker.internal:*","192.168.0.2:*"],
        allowed_origins=["http://localhost:*","http://127.0.0.1:*","http://host.docker.internal:*"])
    mcp.run(transport="streamable-http",host=os.getenv("MCP_HOST","0.0.0.0"),
        port=int(os.getenv("MCP_PORT","8100")),transport_security=security)

if __name__=="__main__":
    main()
