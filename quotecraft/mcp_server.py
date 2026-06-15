"""QUOTECRAFT MCP server — exposes the proposal renderer as an MCP tool."""
from __future__ import annotations
import json
import sys


def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-quotecraft[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print(
            "Install the MCP extra: pip install 'cognis-quotecraft[mcp]'",
            file=sys.stderr,
        )
        return 1

    from quotecraft.core import QuoteError, load_proposal, render_text

    app = FastMCP("quotecraft")

    @app.tool()
    def quotecraft_render(proposal_path: str) -> str:
        """Render a YAML proposal file and return a text summary with totals."""
        try:
            prop = load_proposal(proposal_path)
        except FileNotFoundError:
            return json.dumps({"error": f"File not found: {proposal_path}"})
        except QuoteError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({"ok": True, "preview": render_text(prop)})

    app.run()
    return 0
