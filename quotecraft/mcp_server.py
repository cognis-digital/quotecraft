"""QUOTECRAFT MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from quotecraft.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-quotecraft[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-quotecraft[mcp]'")
        return 1
    app = FastMCP("quotecraft")

    @app.tool()
    def quotecraft_scan(target: str) -> str:
        """Proposal / quote / SOW generator — YAML to branded PDF. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
