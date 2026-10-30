"""Податковий облік (ПО) паралельно до бухгалтерського (БО) і податкові різниці.

Posting: ledger.post_entries calls post_rows(), ledger.cancel_entries calls cancel_rows().
Reports: tax_differences() is used by the API, the report page and the profit tax return (T-442).
Accounting policy is T-445 (not built): the switch is UA Organization.keep_tax_accounting.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.utils import next_names, std_columns

LEDGER = "UA Tax Ledger Entry"
ITEM = "UA Tax Difference Item"
THRESHOLD = 40_000_000  # ПКУ 134.1.1 (the dated setting is T-458)
LOW_TAX_RATE = 0.04
INCOME_ACCOUNT = "70"
READERS = ("UA Accountant", "UA Accounting Manager", "UA Chief Accountant", "System Manager")

AMORT = "Амортизація"
RESERVE = "Резерви та забезпечення"
LOSSES = "Збитки минулих років"
TRANSFER = "Трансфертне ціноутворення"
NON_RES = "Платежі нерезидентам"
LOW_TAX = "Платежі в юрисдикції з низьким рівнем оподаткування"
KINDS = (AMORT, RESERVE, LOSSES, TRANSFER, NON_RES, LOW_TAX)

ARTICLE = {
    AMORT: "ст. 138.3, 138.8 ПКУ",
    RESERVE: "ст. 139.2 ПКУ",
    LOSSES: "ст. 150 ПКУ",
    TRANSFER: "ст. 39 ПКУ",
    NON_RES: "ст. 140.5.7 ПКУ",
    LOW_TAX: "ст. 141 ПКУ",
}

LEDGER_FIELDS = [
    "posting_date", "period", "organization", "registrar_type", "registrar", "line_no",
    "account_dr", "account_cr", "amount_book", "amount_tax", "difference", "content",
]  # fmt: skip


# ---------------------------------------------------------------- register


def post_rows(doc, rows, entries):
    """Write the ПО rows that go with the БО rows just posted (`rows` are built rows)."""
    keep = {}
    values = []
    for row, e in zip(rows, entries, strict=True):
        org = row["organization"]
        if org not in keep:
            keep[org] = frappe.db.get_value("UA Organization", org, "keep_tax_accounting")
        if not keep[org]:
            continue
        book = flt(row["amount"], 2)
        tax = e.get("tax_amount")
        tax = book if tax in (None, "") else flt(tax, 2)
        if tax < 0:
            frappe.throw(_("Проводка {0}: сума ПО не може бути від'ємною").format(row["line_no"]))
        values.append({**row, "amount_book": book, "amount_tax": tax, "difference": flt(book - tax, 2)})
    if not values:
        return
    std = std_columns()
    names = next_names(LEDGER, len(values))
    frappe.db.bulk_insert(
        LEDGER,
        ["name", *LEDGER_FIELDS, *std],
        [[n, *[v[f] for f in LEDGER_FIELDS], *std.values()] for n, v in zip(names, values, strict=True)],
    )


def cancel_rows(doc):
    frappe.db.delete(LEDGER, {"registrar_type": doc.doctype, "registrar": doc.name})


def _check_access(organization=None):
    frappe.only_for(READERS)
    if organization:
        frappe.has_permission("UA Organization", "read", doc=organization, throw=True)


def ledger_balance(organization, account, date):
    """{book, tax}: Дт - Кт of the account (with sub-accounts) at the date."""
    from ua_accounting.reporting.chart import Chart

    accounts = Chart().expand([account]) or [account]
    out = {"book": 0.0, "tax": 0.0}
    for side, sign in (("account_dr", 1), ("account_cr", -1)):
        row = frappe.db.sql(
            f"""select coalesce(sum(amount_book), 0), coalesce(sum(amount_tax), 0) from `tab{LEDGER}`
            where organization = %s and posting_date <= %s and {side} in %s""",
            (organization, getdate(date), accounts),
        )[0]
        out["book"] += sign * flt(row[0])
        out["tax"] += sign * flt(row[1])
    return {"book": flt(out["book"], 2), "tax": flt(out["tax"], 2)}


# ---------------------------------------------------------------- differences


def annual_income(organization, year):
    """Net income of the year: credit turnover of the accounts 70 (VAT is on 64, not here)."""
    row = frappe.db.sql(
        """select coalesce(sum(amount), 0) from `tabUA Accounting Entry`
        where organization = %s and posting_date between %s and %s and account_cr like %s""",
        (organization, f"{year}-01-01", f"{year}-12-31", INCOME_ACCOUNT + "%"),
    )
    return flt(row[0][0], 2)


def adjustment(kind, book, tax):
    """Effect on the financial result before tax (ПКУ ст. 138–141)."""
    if kind in (AMORT, RESERVE, NON_RES):
        return flt(book - tax, 2)
    if kind == TRANSFER:
        return flt(tax - book, 2)
    if kind == LOSSES:
        return flt(-tax, 2)
    if kind == LOW_TAX:
        return flt(LOW_TAX_RATE * book, 2)
    return 0.0


def _ledger_kind(account_dr, account_cr):
    """Kind of a difference that comes from the tax register; None when it has no ПКУ article."""
    cr = account_cr or ""
    if cr.startswith(("13", "14")):
        return AMORT
    if cr.startswith("47"):
        return RESERVE
    return None


def tax_differences(organization, date_from, date_to):
    _check_access(organization)
    date_from, date_to = getdate(date_from), getdate(date_to)
    income = annual_income(organization, date_to.year - 1)
    keep = frappe.db.get_value("UA Organization", organization, "keep_tax_accounting")
    required = bool(keep) and income > THRESHOLD
    result = {"required": required, "threshold": THRESHOLD, "income": income, "rows": [], "total_adjustment": 0}
    if not required:
        return result

    sums = {}

    def add(kind, book, tax):
        s = sums.setdefault(kind, [0.0, 0.0])
        s[0] += flt(book)
        s[1] += flt(tax)

    for r in frappe.db.sql(
        f"""select account_dr, account_cr, amount_book, amount_tax from `tab{LEDGER}`
        where organization = %s and posting_date between %s and %s and difference != 0""",
        (organization, date_from, date_to),
        as_dict=True,
    ):
        kind = _ledger_kind(r.account_dr, r.account_cr)
        if kind:
            add(kind, r.amount_book, r.amount_tax)
    for r in frappe.db.sql(
        f"""select kind, book_amount, tax_amount from `tab{ITEM}`
        where organization = %s and docstatus = 1 and posting_date between %s and %s""",
        (organization, date_from, date_to),
        as_dict=True,
    ):
        add(r.kind, r.book_amount, r.tax_amount)

    rows = []
    for kind in KINDS:
        if kind not in sums:
            continue
        book, tax = (flt(v, 2) for v in sums[kind])
        rows.append(
            {
                "kind": kind,
                "article": ARTICLE[kind],
                "book_amount": book,
                "tax_amount": tax,
                "adjustment": adjustment(kind, book, tax),
            }
        )
    result["rows"] = rows
    result["total_adjustment"] = flt(sum(r["adjustment"] for r in rows), 2)
    return result


def profit_tax_lines(organization, date_from, date_to):
    """Data of the profit tax return (T-442): line 02 and one appendix line РІ.<n> per difference row."""
    res = tax_differences(organization, date_from, date_to)
    lines = [
        {"code": f"РІ.{i}", "kind": r["kind"], "article": r["article"], "value": r["adjustment"]}
        for i, r in enumerate(res["rows"], start=1)
    ]
    return {"02": res["total_adjustment"], "appendix": lines, "required": res["required"]}
