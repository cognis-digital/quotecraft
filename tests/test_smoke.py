"""Smoke tests for QUOTECRAFT. Standard library only, no network."""
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
