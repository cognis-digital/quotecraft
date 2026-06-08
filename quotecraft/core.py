"""Core engine for QUOTECRAFT.

Parses a minimal-but-real subset of YAML (no PyYAML dependency), builds a
Proposal model, computes line-item / discount / tax totals, and renders a real
single-page (auto-paginating) PDF 1.4 document with no external libraries.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any


class QuoteError(Exception):
    """Raised on invalid input or proposal data."""


# ---------------------------------------------------------------------------
# Minimal YAML parser (supports the subset QUOTECRAFT documents use:
# scalars, nested maps via indentation, and lists of maps via '- ').
# ---------------------------------------------------------------------------

def _coerce(raw: str) -> Any:
    s = raw.strip()
    if s == "" or s in ("~", "null", "None"):
        return None
    if (s[0] == s[-1]) and s[0] in ("'", '"') and len(s) >= 2:
        return s[1:-1]
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if "." not in s and "e" not in low:
            return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_yaml(text: str) -> Any:
    """Parse the supported YAML subset into Python dicts/lists/scalars."""
    raw_lines = text.splitlines()
    lines: list[tuple[int, str]] = []
    for ln in raw_lines:
        # strip comments that are not inside quotes (best-effort)
        stripped = ln.split(" #", 1)[0] if " #" in ln else ln
        if stripped.lstrip().startswith("#"):
            continue
        if stripped.strip() == "":
            continue
        lines.append((_indent(stripped), stripped.rstrip()))

    pos = 0

    def parse_block(min_indent: int) -> Any:
        nonlocal pos
        if pos >= len(lines):
            return None
        indent, content = lines[pos]
        if content.lstrip().startswith("- ") or content.strip() == "-":
            return parse_list(indent)
        return parse_map(indent)

    def parse_list(indent: int) -> list:
        nonlocal pos
        items: list = []
        while pos < len(lines):
            cur_indent, content = lines[pos]
            if cur_indent < indent or not (
                content.lstrip().startswith("- ") or content.strip() == "-"
            ):
                break
            if cur_indent != indent:
                break
            body = content.lstrip()[1:].lstrip()
            if body == "":
                pos += 1
                items.append(parse_block(indent + 1))
                continue
            if ":" in body and not _looks_like_url(body):
                # inline first key of a map item; rewrite line and parse a map
                inline_indent = cur_indent + content.lstrip().index("- ") + 2
                lines[pos] = (inline_indent, " " * inline_indent + body)
                items.append(parse_map(inline_indent))
            else:
                items.append(_coerce(body))
                pos += 1
        return items

    def parse_map(indent: int) -> dict:
        nonlocal pos
        result: dict = {}
        while pos < len(lines):
            cur_indent, content = lines[pos]
            if cur_indent < indent:
                break
            if cur_indent > indent:
                break
            stripped = content.strip()
            if stripped.startswith("- "):
                break
            if ":" not in stripped:
                raise QuoteError(f"Malformed YAML line: {content!r}")
            key, _, rest = stripped.partition(":")
            key = key.strip()
            rest = rest.strip()
            pos += 1
            if rest == "":
                if pos < len(lines) and lines[pos][0] > indent:
                    result[key] = parse_block(lines[pos][0])
                else:
                    result[key] = None
            else:
                result[key] = _coerce(rest)
        return result

    if not lines:
        return {}
    return parse_block(lines[0][0])


def _looks_like_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass
class LineItem:
    description: str
    qty: Decimal
    unit_price: Decimal
    unit: str = ""

    @property
    def amount(self) -> Decimal:
        return (self.qty * self.unit_price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


@dataclass
class Proposal:
    title: str
    client: str
    items: list[LineItem]
    currency: str = "USD"
    from_name: str = ""
    number: str = ""
    date: str = ""
    valid_until: str = ""
    notes: str = ""
    tax_rate: Decimal = Decimal("0")
    discount_pct: Decimal = Decimal("0")
    accent: str = "#1a5276"
    totals: dict = field(default_factory=dict)


_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "C$", "AUD": "A$"}


def _dec(value: Any, fieldname: str) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise QuoteError(f"Invalid numeric value for {fieldname!r}: {value!r}")


def build_proposal(data: dict) -> Proposal:
    if not isinstance(data, dict):
        raise QuoteError("Top-level YAML must be a mapping.")
    title = data.get("title")
    client = data.get("client")
    if not title:
        raise QuoteError("Proposal is missing required field: 'title'.")
    if not client:
        raise QuoteError("Proposal is missing required field: 'client'.")

    raw_items = data.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        raise QuoteError("Proposal must contain at least one line item under 'items'.")

    items: list[LineItem] = []
    for i, it in enumerate(raw_items, start=1):
        if not isinstance(it, dict):
            raise QuoteError(f"Line item #{i} must be a mapping.")
        desc = it.get("description") or it.get("desc")
        if not desc:
            raise QuoteError(f"Line item #{i} is missing 'description'.")
        qty = _dec(it.get("qty", it.get("quantity", 1)), f"item {i} qty")
        price = _dec(it.get("unit_price", it.get("price", 0)), f"item {i} unit_price")
        items.append(
            LineItem(
                description=str(desc),
                qty=qty,
                unit_price=price,
                unit=str(it.get("unit", "") or ""),
            )
        )

    today = _dt.date.today().isoformat()
    prop = Proposal(
        title=str(title),
        client=str(client),
        items=items,
        currency=str(data.get("currency", "USD")),
        from_name=str(data.get("from", data.get("from_name", "")) or ""),
        number=str(data.get("number", "") or ""),
        date=str(data.get("date", today) or today),
        valid_until=str(data.get("valid_until", "") or ""),
        notes=str(data.get("notes", "") or ""),
        tax_rate=_dec(data.get("tax_rate", 0), "tax_rate"),
        discount_pct=_dec(data.get("discount_pct", 0), "discount_pct"),
        accent=str(data.get("accent", "#1a5276") or "#1a5276"),
    )
    prop.totals = compute_totals(prop)
    return prop


def load_proposal(path: str) -> Proposal:
    with open(path, "r", encoding="utf-8") as fh:
        data = parse_yaml(fh.read())
    return build_proposal(data)


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_totals(prop: Proposal) -> dict:
    subtotal = sum((it.amount for it in prop.items), Decimal("0"))
    subtotal = _q(subtotal)
    discount = _q(subtotal * prop.discount_pct / Decimal("100"))
    taxable = subtotal - discount
    tax = _q(taxable * prop.tax_rate / Decimal("100"))
    total = _q(taxable + tax)
    return {
        "subtotal": subtotal,
        "discount": discount,
        "discount_pct": prop.discount_pct,
        "taxable": _q(taxable),
        "tax": tax,
        "tax_rate": prop.tax_rate,
        "total": total,
        "currency": prop.currency,
        "line_count": len(prop.items),
    }


def money(value: Decimal, currency: str) -> str:
    sym = _CURRENCY_SYMBOLS.get(currency.upper(), "")
    amt = f"{_q(value):,.2f}"
    if sym:
        return f"{sym}{amt}"
    return f"{amt} {currency}"


# ---------------------------------------------------------------------------
# Text rendering (used by CLI 'preview' / table output)
# ---------------------------------------------------------------------------

def render_text(prop: Proposal) -> str:
    t = prop.totals or compute_totals(prop)
    cur = prop.currency
    out: list[str] = []
    out.append(prop.title)
    out.append("=" * len(prop.title))
    meta = []
    if prop.number:
        meta.append(f"No. {prop.number}")
    if prop.date:
        meta.append(f"Date: {prop.date}")
    if prop.valid_until:
        meta.append(f"Valid until: {prop.valid_until}")
    if meta:
        out.append("  |  ".join(meta))
    if prop.from_name:
        out.append(f"From: {prop.from_name}")
    out.append(f"To:   {prop.client}")
    out.append("")
    out.append(f"{'Description':40} {'Qty':>6} {'Unit Price':>14} {'Amount':>14}")
    out.append("-" * 78)
    for it in prop.items:
        desc = (it.description[:38] + "..") if len(it.description) > 40 else it.description
        out.append(
            f"{desc:40} {it.qty!s:>6} {money(it.unit_price, cur):>14} "
            f"{money(it.amount, cur):>14}"
        )
    out.append("-" * 78)
    out.append(f"{'Subtotal':>62} {money(t['subtotal'], cur):>14}")
    if t["discount"] > 0:
        out.append(f"{('Discount ' + str(t['discount_pct']) + '%'):>62} "
                   f"-{money(t['discount'], cur):>13}")
    if t["tax"] > 0:
        out.append(f"{('Tax ' + str(t['tax_rate']) + '%'):>62} {money(t['tax'], cur):>14}")
    out.append(f"{'TOTAL':>62} {money(t['total'], cur):>14}")
    if prop.notes:
        out.append("")
        out.append("Notes:")
        out.append(prop.notes)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# PDF rendering (PDF 1.4, no dependencies). Uses Helvetica core fonts.
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return (r, g, b)
    except (ValueError, IndexError):
        return (0.10, 0.32, 0.46)


class _Content:
    """Accumulates PDF page content stream operators."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def text(self, x: float, y: float, s: str, size: int = 10,
             font: str = "F1", rgb: tuple[float, float, float] = (0, 0, 0)) -> None:
        r, g, b = rgb
        self.parts.append(
            f"{r:.3f} {g:.3f} {b:.3f} rg BT /{font} {size} Tf "
            f"1 0 0 1 {x:.2f} {y:.2f} Tm ({_esc(s)}) Tj ET"
        )

    def rect(self, x: float, y: float, w: float, h: float,
             rgb: tuple[float, float, float]) -> None:
        r, g, b = rgb
        self.parts.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")

    def line(self, x1: float, y1: float, x2: float, y2: float,
             rgb: tuple[float, float, float] = (0.7, 0.7, 0.7)) -> None:
        r, g, b = rgb
        self.parts.append(
            f"{r:.3f} {g:.3f} {b:.3f} RG 0.7 w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S"
        )

    def render(self) -> bytes:
        return ("\n".join(self.parts)).encode("latin-1", "replace")


def render_pdf(prop: Proposal) -> bytes:
    """Render the proposal to a multi-page-aware PDF document (bytes)."""
    t = prop.totals or compute_totals(prop)
    cur = prop.currency
    accent = _hex_to_rgb(prop.accent)
    dark = (0.13, 0.13, 0.13)
    gray = (0.45, 0.45, 0.45)

    W, H = 612.0, 792.0  # US Letter
    ML, MR = 54.0, 558.0
    pages: list[_Content] = []

    def new_page() -> tuple[_Content, float]:
        c = _Content()
        # header band
        c.rect(0, H - 90, W, 90, accent)
        c.text(ML, H - 50, prop.title[:60], size=20, font="F2", rgb=(1, 1, 1))
        if prop.from_name:
            c.text(ML, H - 72, prop.from_name[:80], size=10, font="F1", rgb=(1, 1, 1))
        pages.append(c)
        return c, H - 120.0

    c, y = new_page()

    # meta block
    meta_lines = []
    if prop.number:
        meta_lines.append(f"Proposal No: {prop.number}")
    if prop.date:
        meta_lines.append(f"Date: {prop.date}")
    if prop.valid_until:
        meta_lines.append(f"Valid until: {prop.valid_until}")
    c.text(ML, y, f"Prepared for: {prop.client}", size=12, font="F2", rgb=dark)
    yy = y
    for m in meta_lines:
        c.text(MR - 150, yy, m, size=9, font="F1", rgb=gray)
        yy -= 13
    y -= 34

    # table header
    def table_header(c: _Content, y: float) -> float:
        c.rect(ML, y - 4, MR - ML, 18, (0.92, 0.92, 0.92))
        c.text(ML + 4, y, "Description", size=9, font="F2", rgb=dark)
        c.text(MR - 200, y, "Qty", size=9, font="F2", rgb=dark)
        c.text(MR - 150, y, "Unit Price", size=9, font="F2", rgb=dark)
        c.text(MR - 60, y, "Amount", size=9, font="F2", rgb=dark)
        return y - 22

    y = table_header(c, y)

    for it in prop.items:
        if y < 140:
            c, y = new_page()
            y = table_header(c, y)
        desc = it.description
        if len(desc) > 52:
            desc = desc[:50] + ".."
        c.text(ML + 4, y, desc, size=9, rgb=dark)
        c.text(MR - 200, y, f"{it.qty}{(' ' + it.unit) if it.unit else ''}", size=9, rgb=dark)
        c.text(MR - 150, y, money(it.unit_price, cur), size=9, rgb=dark)
        c.text(MR - 60, y, money(it.amount, cur), size=9, rgb=dark)
        c.line(ML, y - 6, MR, y - 6, (0.85, 0.85, 0.85))
        y -= 20

    # totals box
    if y < 160:
        c, y = new_page()
    y -= 8
    box_top = y

    def total_row(label: str, value: str, bold: bool = False) -> None:
        nonlocal y
        f = "F2" if bold else "F1"
        c.text(MR - 200, y, label, size=10, font=f, rgb=dark)
        c.text(MR - 60, y, value, size=10, font=f, rgb=dark)
        y -= 16

    total_row("Subtotal", money(t["subtotal"], cur))
    if t["discount"] > 0:
        total_row(f"Discount ({t['discount_pct']}%)", "-" + money(t["discount"], cur))
    if t["tax"] > 0:
        total_row(f"Tax ({t['tax_rate']}%)", money(t["tax"], cur))
    c.line(MR - 205, y + 6, MR, y + 6, accent)
    y -= 4
    c.rect(MR - 210, y - 4, 210, 22, accent)
    c.text(MR - 200, y + 2, "TOTAL", size=12, font="F2", rgb=(1, 1, 1))
    c.text(MR - 60, y + 2, money(t["total"], cur), size=12, font="F2", rgb=(1, 1, 1))
    y -= 30
    _ = box_top

    # notes
    if prop.notes:
        if y < 120:
            c, y = new_page()
        c.text(ML, y, "Notes & Terms", size=11, font="F2", rgb=accent)
        y -= 16
        for line in _wrap(prop.notes, 95):
            if y < 60:
                c, y = new_page()
            c.text(ML, y, line, size=9, rgb=gray)
            y -= 12

    # footer on every page
    for i, page in enumerate(pages, start=1):
        page.text(ML, 36, f"Generated by QUOTECRAFT  -  Page {i} of {len(pages)}",
                  size=8, rgb=(0.6, 0.6, 0.6))

    return _assemble_pdf(pages, W, H)


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            if len(cur) + 1 + len(w) <= width:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _assemble_pdf(pages: list[_Content], W: float, H: float) -> bytes:
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    resources = (
        f"<< /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >>".encode("latin-1")
    )

    pages_obj_id = len(objects) + 1  # reserve next id for Pages tree
    # placeholder so ids line up; we will fill after children created
    add(b"PLACEHOLDER_PAGES")

    page_ids: list[int] = []
    for content in pages:
        stream = content.render()
        content_id = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
        page_dict = (
            f"<< /Type /Page /Parent {pages_obj_id} 0 R "
            f"/MediaBox [0 0 {W:.0f} {H:.0f}] /Resources "
        ).encode("latin-1") + resources + (
            f" /Contents {content_id} 0 R >>".encode("latin-1")
        )
        page_ids.append(add(page_dict))

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_obj_id - 1] = (
        f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode("latin-1")
    )

    catalog_id = add(f"<< /Type /Catalog /Pages {pages_obj_id} 0 R >>".encode("latin-1"))

    # serialize
    out = bytearray()
    out += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1") + obj + b"\nendobj\n"

    xref_pos = len(out)
    n = len(objects) + 1
    out += f"xref\n0 {n}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {n} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(out)
