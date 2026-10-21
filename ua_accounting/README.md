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

## Documents (module `UA Documents`)

| Document | DocType | Entries |
|---|---|---|
| Замовлення покупця / постачальнику | `UA Customer Order`, `UA Supplier Order` | none, only status |
| Реалізація товарів та послуг | `UA Sales Invoice` | Dt 361 Ct 70x, Dt 704 Ct 641, Dt 90x Ct 281/26 (average cost), Dt 681 Ct 361, Dt 641 Ct 643 |
| Надходження товарів та послуг | `UA Purchase Receipt` | Dt 281/201/26/92 Ct 631, Dt 644 Ct 631, Dt 641 Ct 644, Dt 631 Ct 371 |
| Надходження коштів | `UA Cash Receipt` | Dt 311/301 Ct 361 or 681, Dt 643 Ct 641 on an advance |
| Витрата коштів | `UA Cash Payment` | Dt 631 or 371 Ct 311/301, Dt 641 Ct 644 on an advance |
| Операція (бухгалтерська) | `UA Journal Operation` | typed by hand, also for opening balances |

Documents post on submit and delete their entries on cancel (`ua_accounting/accounting/documents.py`).
Numbers: `<prefix of the organization>-<code>-<yy>-<counter>`, for example `AB-SI-26-00001`.
Foreign accounts (362, 632, 312, 302) are used when the document currency is not the base one.
The VAT register gets a row once, at the first event (advance payment or shipment).

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

## Reports

Pages in the workspace, section "Звіти": `ua-osv` (Оборотно-сальдова відомість),
`ua-osv-account` (ОСВ по рахунку), `ua-account-card` (Картка рахунку).
Click an account row in OSV to open OSV by account. Click a row there to open the account card.
Click a document in the card to open it. Print and Excel are in the page toolbar.

Server code is in `ua_accounting/reporting/`:

- `filters.py` one filter format for all reports (period, organizations, accounts, subconto, currency).
- `query.py` the shared query layer. Whole months are read from the monthly totals
  (`UA Account Turnover`). Only the partial months at the edges are read from entries.
  A subconto that is "turnover only" is not in the totals, so such accounts are read from entries.
- `balance.py` rows opening / turnover / closing for OSV and OSV by account.
- `api.py` whitelisted methods. A new report is `build(filters) -> table model` plus one line in `REPORTS`.

Client code: `public/js/ua_report.js` (one page class for all reports) and `public/css/ua_report.css`.

## Tests

Tests need a bench site with the app installed:
`bench --site mysite run-tests --app ua_accounting`.
