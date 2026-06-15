"""Smoke tests for QUOTECRAFT. Standard library only, no network."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quotecraft import (  # noqa: E402
    TOOL_NAME,
    TOOL_VERSION,
    build_proposal,
    compute_totals,
    parse_yaml,
    render_pdf,
    render_text,
    QuoteError,
)
from quotecraft.cli import main  # noqa: E402


SAMPLE = """
title: Test Proposal
client: Acme Co
from: My Agency
currency: USD
discount_pct: 10
tax_rate: 8.25
items:
  - description: Design
    qty: 1
    unit_price: 1000
  - description: Dev hours
    qty: 10
    unit: hours
    unit_price: 100
"""


class TestYAML(unittest.TestCase):
    def test_parse_basic(self):
        data = parse_yaml(SAMPLE)
        self.assertEqual(data["title"], "Test Proposal")
        self.assertEqual(data["client"], "Acme Co")
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["items"][1]["unit"], "hours")
        self.assertEqual(data["items"][1]["qty"], 10)


class TestTotals(unittest.TestCase):
    def test_compute(self):
        prop = build_proposal(parse_yaml(SAMPLE))
        t = prop.totals
        self.assertEqual(t["subtotal"], Decimal("2000.00"))
        self.assertEqual(t["discount"], Decimal("200.00"))
        self.assertEqual(t["taxable"], Decimal("1800.00"))
        self.assertEqual(t["tax"], Decimal("148.50"))
        self.assertEqual(t["total"], Decimal("1948.50"))
        self.assertEqual(t["line_count"], 2)

    def test_recompute_matches(self):
        prop = build_proposal(parse_yaml(SAMPLE))
        self.assertEqual(compute_totals(prop)["total"], prop.totals["total"])


class TestValidation(unittest.TestCase):
    def test_missing_title(self):
        with self.assertRaises(QuoteError):
            build_proposal({"client": "x", "items": [{"description": "a"}]})

    def test_no_items(self):
        with self.assertRaises(QuoteError):
            build_proposal({"title": "t", "client": "c", "items": []})

    def test_item_needs_description(self):
        with self.assertRaises(QuoteError):
            build_proposal({"title": "t", "client": "c",
                            "items": [{"qty": 1, "unit_price": 5}]})


class TestRender(unittest.TestCase):
    def test_pdf_bytes(self):
        prop = build_proposal(parse_yaml(SAMPLE))
        pdf = render_pdf(prop)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", pdf)
        self.assertIn(b"/Type /Catalog", pdf)
        self.assertGreater(len(pdf), 800)

    def test_text(self):
        prop = build_proposal(parse_yaml(SAMPLE))
        txt = render_text(prop)
        self.assertIn("Test Proposal", txt)
        self.assertIn("TOTAL", txt)
        self.assertIn("Acme Co", txt)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.yaml = os.path.join(self.dir, "p.yaml")
        with open(self.yaml, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE)

    def test_total_json(self):
        rc = main(["--format", "json", "total", self.yaml])
        self.assertEqual(rc, 0)

    def test_render_creates_pdf(self):
        out = os.path.join(self.dir, "out.pdf")
        rc = main(["render", self.yaml, "-o", out])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(out))
        with open(out, "rb") as fh:
            self.assertTrue(fh.read(8).startswith(b"%PDF"))

    def test_missing_file_nonzero(self):
        rc = main(["--format", "json", "total", os.path.join(self.dir, "nope.yaml")])
        self.assertNotEqual(rc, 0)

    def test_version_subprocess(self):
        proc = subprocess.run(
            [sys.executable, "-m", "quotecraft", "--version"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn(TOOL_VERSION, proc.stdout)
        self.assertIn(TOOL_NAME, proc.stdout)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Hardening tests — error paths, edge cases, input validation
# ---------------------------------------------------------------------------

class TestCLIErrorPaths(unittest.TestCase):
    """CLI must return a non-zero exit code and print to stderr on bad input."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _run(self, argv):
        """Return (returncode, stdout, stderr)."""
        import io
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            rc = main(argv)
        finally:
            out = sys.stdout.getvalue()
            err = sys.stderr.getvalue()
            sys.stdout, sys.stderr = old_out, old_err
        return rc, out, err

    def test_missing_file_exits_2(self):
        rc, out, err = self._run(["total", "/no/such/file.yaml"])
        self.assertEqual(rc, 2)
        self.assertIn("not found", err.lower())
        self.assertEqual(out, "")

    def test_missing_file_json_exits_2(self):
        rc, out, err = self._run(["--format", "json", "total", "/no/such/file.yaml"])
        self.assertEqual(rc, 2)
        payload = json.loads(out if out.strip() else '{"error":""}')
        # JSON error lands on stderr too
        if not out.strip():
            payload = json.loads(err)
        self.assertIn("error", payload)

    def test_bad_yaml_not_mapping_exits_1(self):
        p = os.path.join(self.dir, "list.yaml")
        with open(p, "w") as f:
            f.write("- one\n- two\n")
        rc, out, err = self._run(["total", p])
        self.assertEqual(rc, 1)
        self.assertIn("mapping", err.lower())

    def test_binary_file_exits_cleanly(self):
        p = os.path.join(self.dir, "bin.yaml")
        with open(p, "wb") as f:
            f.write(b"\xff\xfe\x00\x00garbage")
        rc, out, err = self._run(["total", p])
        self.assertNotEqual(rc, 0)
        # No raw traceback on stderr
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Traceback", out)

    def test_render_bad_input_exits_1(self):
        p = os.path.join(self.dir, "bad.yaml")
        with open(p, "w") as f:
            f.write("title: t\n# no client or items\n")
        rc, out, err = self._run(["render", p])
        self.assertNotEqual(rc, 0)


class TestCoreValidation(unittest.TestCase):
    """build_proposal and helpers must reject out-of-range values cleanly."""

    def _minimal(self, **kwargs):
        base = {
            "title": "T",
            "client": "C",
            "items": [{"description": "x", "qty": 1, "unit_price": 10}],
        }
        base.update(kwargs)
        return base

    def test_negative_tax_rate_raises(self):
        with self.assertRaises(QuoteError):
            build_proposal(self._minimal(tax_rate=-1))

    def test_tax_rate_over_100_raises(self):
        with self.assertRaises(QuoteError):
            build_proposal(self._minimal(tax_rate=101))

    def test_negative_discount_raises(self):
        with self.assertRaises(QuoteError):
            build_proposal(self._minimal(discount_pct=-0.01))

    def test_discount_over_100_raises(self):
        with self.assertRaises(QuoteError):
            build_proposal(self._minimal(discount_pct=100.01))

    def test_100_percent_discount_allowed(self):
        prop = build_proposal(self._minimal(discount_pct=100))
        self.assertEqual(prop.totals["total"], Decimal("0.00"))

    def test_invalid_numeric_field_raises(self):
        with self.assertRaises(QuoteError):
            build_proposal(self._minimal(tax_rate="notanumber"))

    def test_missing_client_raises(self):
        with self.assertRaises(QuoteError):
            build_proposal({"title": "T", "items": [{"description": "x"}]})

    def test_load_proposal_bad_encoding_raises_quoteerror(self):
        import tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, "enc.yaml")
        with open(p, "wb") as f:
            f.write(b"\xff\xfe bad bytes")
        from quotecraft.core import load_proposal
        with self.assertRaises(QuoteError) as ctx:
            load_proposal(p)
        self.assertIn("UTF-8", str(ctx.exception))


class TestVersionExport(unittest.TestCase):
    """TOOL_NAME and TOOL_VERSION must be correct via both core and package."""

    def test_tool_name_and_version_from_core(self):
        from quotecraft.core import TOOL_NAME, TOOL_VERSION
        self.assertEqual(TOOL_NAME, "quotecraft")
        self.assertTrue(len(TOOL_VERSION) >= 5)  # at least "0.1.0"

    def test_version_matches_package(self):
        from quotecraft import TOOL_VERSION as pkg_ver
        from quotecraft.core import TOOL_VERSION as core_ver
        self.assertEqual(pkg_ver, core_ver)
