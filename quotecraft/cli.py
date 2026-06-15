"""Command-line interface for QUOTECRAFT."""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

from . import TOOL_NAME, TOOL_VERSION
from .core import (
    QuoteError,
    compute_totals,
    load_proposal,
    money,
    render_pdf,
    render_text,
)


def _jsonable(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(repr(obj))


def _proposal_dict(prop) -> dict:
    t = prop.totals or compute_totals(prop)
    return {
        "title": prop.title,
        "client": prop.client,
        "from": prop.from_name,
        "number": prop.number,
        "date": prop.date,
        "valid_until": prop.valid_until,
        "currency": prop.currency,
        "items": [
            {
                "description": it.description,
                "qty": float(it.qty),
                "unit": it.unit,
                "unit_price": float(it.unit_price),
                "amount": float(it.amount),
            }
            for it in prop.items
        ],
        "totals": {k: (float(v) if isinstance(v, Decimal) else v) for k, v in t.items()},
    }


def _emit(payload: dict, fmt: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    if fmt == "json":
        print(json.dumps(payload, indent=2, default=_jsonable), file=stream)
    else:
        _emit_table(payload, err=err)


def _emit_table(payload: dict, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    if "error" in payload:
        print(f"ERROR: {payload['error']}", file=stream)
        return
    if payload.get("action") == "render":
        print(f"Wrote {payload['bytes']} bytes to {payload['output']}")
        print(f"Pages: ~{payload.get('pages', '?')}  Total: {payload['total_display']}")
        return
    # build / preview
    p = payload["proposal"]
    t = p["totals"]
    print(p["title"])
    print("=" * len(p["title"]))
    print(f"Client: {p['client']}    Currency: {p['currency']}")
    print(f"Line items: {t['line_count']}")
    print(f"{'Description':40} {'Qty':>6} {'Amount':>14}")
    print("-" * 62)
    for it in p["items"]:
        desc = it["description"][:40]
        print(f"{desc:40} {it['qty']:>6} {it['amount']:>14,.2f}")
    print("-" * 62)
    print(f"{'Subtotal':>46} {t['subtotal']:>14,.2f}")
    if t["discount"]:
        print(f"{'Discount':>46} {-t['discount']:>14,.2f}")
    if t["tax"]:
        print(f"{'Tax':>46} {t['tax']:>14,.2f}")
    print(f"{'TOTAL':>46} {t['total']:>14,.2f}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="QUOTECRAFT - turn a YAML proposal into a branded PDF quote / SOW.",
    )
    parser.add_argument("--version", action="version",
                        version=f"{TOOL_NAME} {TOOL_VERSION}")
    parser.add_argument("--format", choices=["table", "json"], default="table",
                        help="output format for command results (default: table)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render", help="render a YAML proposal to a PDF file")
    p_render.add_argument("input", help="path to the proposal YAML file")
    p_render.add_argument("-o", "--output", help="output PDF path (default: <input>.pdf)")

    p_preview = sub.add_parser("preview", help="print a plain-text preview of the proposal")
    p_preview.add_argument("input", help="path to the proposal YAML file")

    p_total = sub.add_parser("total", help="compute and show proposal totals only")
    p_total.add_argument("input", help="path to the proposal YAML file")

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fmt = args.format

    try:
        prop = load_proposal(args.input)
    except FileNotFoundError:
        _emit({"error": f"File not found: {args.input}"}, fmt, err=True)
        return 2
    except PermissionError as e:
        _emit({"error": f"Permission denied reading {args.input}: {e}"}, fmt, err=True)
        return 2
    except OSError as e:
        _emit({"error": f"Could not read {args.input}: {e}"}, fmt, err=True)
        return 2
    except QuoteError as e:
        _emit({"error": str(e)}, fmt, err=True)
        return 1

    if args.command == "render":
        output = args.output or (args.input.rsplit(".", 1)[0] + ".pdf")
        try:
            data = render_pdf(prop)
            with open(output, "wb") as fh:
                fh.write(data)
        except OSError as e:
            _emit({"error": f"Could not write output: {e}"}, fmt, err=True)
            return 2
        t = prop.totals
        _emit(
            {
                "action": "render",
                "output": output,
                "bytes": len(data),
                "total": float(t["total"]),
                "total_display": money(t["total"], prop.currency),
            },
            fmt,
        )
        return 0

    if args.command == "preview":
        if fmt == "json":
            _emit({"proposal": _proposal_dict(prop)}, fmt)
        else:
            print(render_text(prop))
        return 0

    if args.command == "total":
        t = prop.totals
        _emit(
            {
                "proposal": _proposal_dict(prop)
                if fmt == "json"
                else {"title": prop.title, "client": prop.client,
                      "currency": prop.currency, "items": [], "totals":
                      {k: (float(v) if isinstance(v, Decimal) else v)
                       for k, v in t.items()}},
            },
            fmt,
        )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
