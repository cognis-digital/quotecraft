"""QUOTECRAFT - YAML to branded PDF proposal / quote / SOW generator.

Standard-library only. No third-party dependencies.
"""
from .core import (
    Proposal,
    LineItem,
    parse_yaml,
    load_proposal,
    build_proposal,
    compute_totals,
    render_pdf,
    render_text,
    QuoteError,
)

TOOL_NAME = "quotecraft"
TOOL_VERSION = "1.0.0"

__all__ = [
    "Proposal",
    "LineItem",
    "parse_yaml",
    "load_proposal",
    "build_proposal",
    "compute_totals",
    "render_pdf",
    "render_text",
    "QuoteError",
    "TOOL_NAME",
    "TOOL_VERSION",
]
