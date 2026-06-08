# Demo 01 - Basic web redesign proposal

This demo shows QUOTECRAFT turning a single YAML file into a branded,
client-ready PDF quote / statement of work.

The scenario: a small design + dev agency ("Northwind Studio") sends a fixed-fee
proposal to a client ("Riverside Dental Group") for a website redesign. The
proposal mixes fixed deliverables and hourly line items, applies a returning-
client discount, and adds sales tax.

## Input

`proposal.yaml` describes the proposal: branding accent color, the sender,
client, line items (with quantity / unit / unit price), a discount percentage,
a tax rate, and notes / terms.

## Run it

Preview the math as a table:

```
python -m quotecraft preview demos/01-basic/proposal.yaml
```

Get machine-readable totals (for piping into invoicing / CRM tooling):

```
python -m quotecraft --format json total demos/01-basic/proposal.yaml
```

Render the branded PDF:

```
python -m quotecraft render demos/01-basic/proposal.yaml -o northwind_quote.pdf
```

## Expected

- `preview` / `total` show a subtotal of 14,250.00, a 10% returning-client
  discount of 1,425.00, 8.25% tax of 1,058.06, and a grand total of
  **$13,883.06**.
- `render` writes a valid PDF (starts with `%PDF-1.4`) with a colored header
  band, an itemized table, a highlighted TOTAL box, and a notes section.
