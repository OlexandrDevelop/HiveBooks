# ua_accounting

Accounting for Ukraine, like 1C "Бухгалтерія для України". A Frappe v16 app.
It depends only on `frappe`. There is no ERPNext code.

## Install in a dev bench

`bench get-app` cannot install from a subfolder of a repo. Link the folder instead:

```bash
ln -s /path/to/ERP/apps/ua_accounting frappe-bench/apps/ua_accounting
./env/bin/pip install -e apps/ua_accounting
echo ua_accounting >> sites/apps.txt
bench --site mysite install-app ua_accounting
```

Install and every `bench migrate` load the seed data (chart of accounts No. 291,
VAT rates, currencies, units, subconto types). The loader only inserts missing records.

## Content

- Module `UA Core`: `UA Account` (chart, tree), `UA Subconto Type`, `UA Accounting Entry`,
  `UA Account Turnover`, `UA VAT Rate`, `UA VAT Liability Entry`, `UA VAT Credit Entry`, `UA Tax Type`.
- Module `UA Catalogs`: organizations, counterparties, contracts, items, units, warehouses,
  currencies, banks, bank accounts, cash desks, fixed/intangible/low value assets and helpers.
- Workspace `Бухгалтерія`.

## Posting API

```python
from ua_accounting.accounting.ledger import post_entries, cancel_entries, repost_entries

post_entries(doc, [{
    "account_dr": "361", "account_cr": "701", "amount": 1200,
    "subconto_dr": {"Counterparty": cp, "Contract": contract, "SettlementDoc": (doc.doctype, doc.name)},
    "subconto_cr": {"Item": item, "VatRate": "20"},
    "content": "Реалізація",
}])
cancel_entries(doc)   # deletes entries and fixes the monthly totals
```

`posting_date` and `organization` default to the values of `doc`. Subconto is passed by
the name of `UA Subconto Type`. VAT registers: `ua_accounting.accounting.vat.post_vat_entries`.

The full design note is in the task comment "Architect: technical design T-424".

## Tests

Tests need a bench site with the app installed:
`bench --site mysite run-tests --app ua_accounting`.
