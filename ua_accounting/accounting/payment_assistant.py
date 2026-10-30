"""Payment assistant: proposals of payments for due supplier invoices and taxes, and payment orders from them."""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate

from ua_accounting.accounting import deadlines as dl
from ua_accounting.accounting.provisions import round_money
from ua_accounting.accounting.utils import title_of, uk_date, uk_money

RECEIPT = "UA Purchase Receipt"
ORDER = "UA Payment Order"
LIVE = ("Створено", "Експортовано")
SUPPLIER_ACCOUNTS = ("631", "632")
TAX_ACCOUNT = "641"
# tax type -> (quarterly, return function); other types are paid monthly like the ЄСВ report
QUARTERLY = ("CIT", "SINGLE")
PURPOSE_LIMIT = 160


def _items(items):
    if isinstance(items, str):
        items = json.loads(items or "[]")
    return items or []


# ---------------------------------------------------------------- suppliers


def _debts(names):
    """Rest of each receipt in the register 63: credit minus debit of its settlement document."""
    if not names:
        return {}
    rest = {name: 0.0 for name in names}
    for side, sign in (("cr", 1), ("dr", -1)):
        rows = frappe.db.sql(
            f"""select subconto_{side}3 as doc, sum(amount) as amount from `tabUA Accounting Entry`
            where account_{side} in %(accounts)s and subconto_{side}3 in %(names)s group by 1""",
            {"accounts": SUPPLIER_ACCOUNTS, "names": tuple(names)},
            as_dict=True,
        )
        for r in rows:
            rest[r.doc] += sign * flt(r.amount)
    return rest


def _live_orders(organization, basis=None, tax_type=None):
    """Sum of the orders that wait for payment (draft or submitted, not yet paid)."""
    where = ["organization = %(org)s", "docstatus < 2", "status in %(live)s"]
    params = {"org": organization, "live": LIVE}
    if basis:
        where.append("basis_type = %(btype)s and basis = %(basis)s")
        params.update(btype=RECEIPT, basis=basis)
    if tax_type:
        where.append("payment_kind = 'Податок' and tax_type = %(tax)s")
        params["tax"] = tax_type
    return flt(
        frappe.db.sql(f"select coalesce(sum(amount), 0) from `tabUA Payment Order` where {' and '.join(where)}", params)[0][0]
    )


def _vat_share(receipt):
    total = flt(receipt.total_amount)
    return flt(receipt.vat_total) / total if total and flt(receipt.vat_total) > 0 else 0.0


def purpose_of(doc_name, doc_date, vat_amount):
    text = f"Оплата за товари згідно {doc_name} від {uk_date(doc_date)}"
    if flt(vat_amount):
        text += f", у т.ч. ПДВ 20% - {uk_money(vat_amount)} грн"
    else:
        text += ", без ПДВ"
    return text[:PURPOSE_LIMIT]


def default_iban(counterparty):
    rows = frappe.get_all(
        "UA Counterparty Bank Account", filters={"parent": counterparty, "parenttype": "UA Counterparty", "iban": ("is", "set")},
        fields=["iban", "is_default"], order_by="is_default desc, idx asc", limit_page_length=0,
    )
    return rows[0].iban if rows else ""


def supplier_row(receipt, due, day, org_rest=None):
    """One proposal row of a receipt with the rest `due`."""
    due = flt(due, 2)
    vat = round_money(due * _vat_share(receipt))
    return {
        "counterparty": receipt.counterparty,
        "counterparty_title": title_of("UA Counterparty", receipt.counterparty),
        "contract": receipt.contract,
        "doc_type": RECEIPT,
        "doc": receipt.name,
        "doc_date": str(receipt.posting_date),
        "due_date": str(receipt.payment_due_date or receipt.posting_date),
        "amount_due": due,
        "overdue_days": max(0, date_diff(day, receipt.payment_due_date or receipt.posting_date)),
        "vat_amount": vat,
        "purpose": purpose_of(receipt.name, receipt.posting_date, vat),
        "no_iban": not default_iban(receipt.counterparty),
    }


def receipt_due(receipt):
    """Rest of the receipt that is not paid and not in a live order."""
    rest = _debts([receipt.name])[receipt.name]
    return flt(rest - _live_orders(receipt.organization, basis=receipt.name), 2)


def supplier_proposals(organization, day, horizon):
    limit = add_days(day, horizon)
    receipts = frappe.db.sql(
        """select name, organization, posting_date, counterparty, contract, vat_total, total_amount, payment_due_date
        from `tabUA Purchase Receipt` where organization = %s and docstatus = 1
        and coalesce(payment_due_date, posting_date) <= %s
        order by coalesce(payment_due_date, posting_date), posting_date, name""",
        (organization, limit),
        as_dict=True,
    )
    debts = _debts([r.name for r in receipts])
    rows = []
    for r in receipts:
        due = flt(debts[r.name] - _live_orders(organization, basis=r.name), 2)
        if due > 0:
            rows.append(supplier_row(r, due, day))
    return rows


# ---------------------------------------------------------------- taxes


def _first_year(organization, tax_type, day):
    """The year of the oldest accrual of the tax (credit of 641), so no unpaid period is left out."""
    first = frappe.db.sql(
        "select min(posting_date) from `tabUA Accounting Entry` where organization = %s and account_cr = %s and subconto_cr1 = %s",
        (organization, TAX_ACCOUNT, tax_type),
    )[0][0]
    return min(getdate(first).year, day.year) if first else day.year


def _closed_periods(organization, tax_type, day):
    """Reporting periods that ended on or before the day (from the first accrual), oldest first:
    (period_end, payment day, title)."""
    quarterly = tax_type in QUARTERLY
    ends = []
    for year in range(_first_year(organization, tax_type, day), day.year + 1):
        if quarterly:
            ends += [dl.quarter_end(year, q) for q in range(1, 5)]
        else:
            ends += [dl.month_end(year, m) for m in range(1, 13)]
    out = []
    for end in sorted(e for e in ends if e <= day):
        if tax_type == "VAT":
            pay = dl.vat_return(end)[1]
        elif quarterly:
            pay = dl.quarter_return(end)[1]
        else:
            pay = dl.esv_report(end)
        label = dl.quarter_title(end.year, dl.quarter_of(end)) if quarterly else dl.month_title(end.year, end.month)
        out.append((end, pay, label))
    return out


def _sum_641(organization, tax_type, side, until, since=None):
    where = "organization = %s and account_{0} = %s and subconto_{0}1 = %s and posting_date <= %s".format(side)
    params = [organization, TAX_ACCOUNT, tax_type, until]
    if since:
        where += " and posting_date > %s"
        params.append(since)
    return flt(frappe.db.sql(f"select coalesce(sum(amount), 0) from `tabUA Accounting Entry` where {where}", params)[0][0])


def _unpaid_periods(organization, tax_type, day, horizon):
    """Closed periods with an unpaid tax whose payment day is ≤ day + horizon: [(end, pay, label, amount)], oldest first.

    The credit of 641 of each period is paid first-in first-out by all debits of 641 and the live orders.
    """
    periods = _closed_periods(organization, tax_type, day)
    limit = add_days(day, horizon)
    paid = _sum_641(organization, tax_type, "dr", day) + _live_orders(organization, tax_type=tax_type)
    out, previous = [], None
    for end, pay, label in periods:
        accrued = _sum_641(organization, tax_type, "cr", end, previous)
        previous = end
        covered = min(accrued, max(paid, 0.0))
        paid -= covered
        rest = flt(accrued - covered, 2)
        if rest > 0 and pay <= limit:
            out.append((end, pay, label, rest))
    return out


def tax_title(tax_type):
    return frappe.db.get_value("UA Tax Type", tax_type, "tax_name") or tax_type


def tax_account(organization, tax_type):
    rows = frappe.get_all(
        "UA Tax Payment Account", filters={"organization": organization, "tax_type": tax_type}, fields=["*"],
        order_by="creation asc", limit=1,
    )
    return rows[0] if rows else None


def tax_rows(organization, tax_type, day, horizon):
    """One proposal row per closed period with an unpaid tax, oldest first."""
    account = tax_account(organization, tax_type)
    return [
        {
            "tax_type": tax_type,
            "title": f"{tax_title(tax_type)} за {label}",
            "period_end": str(end),
            "due_date": str(pay),
            "amount": amount,
            "overdue_days": max(0, date_diff(day, pay)),
            "budget_code": account.budget_code if account else "",
            "no_account": not account,
        }
        for end, pay, label, amount in _unpaid_periods(organization, tax_type, day, horizon)
    ]


def tax_proposals(organization, day, horizon):
    types = frappe.db.sql(
        "select distinct subconto_cr1 from `tabUA Accounting Entry` where organization = %s and account_cr = %s and subconto_cr1 != ''",
        (organization, TAX_ACCOUNT),
    )
    rows = []
    for (tax_type,) in sorted(types):
        rows += tax_rows(organization, tax_type, day, horizon)
    return rows


def get_proposals(organization, date, horizon_days=0, bank_account=None):
    day, horizon = getdate(date), cint(horizon_days)
    suppliers = supplier_proposals(organization, day, horizon)
    taxes = tax_proposals(organization, day, horizon)
    total = flt(sum(r["amount_due"] for r in suppliers) + sum(r["amount"] for r in taxes), 2)
    return {"suppliers": suppliers, "taxes": taxes, "total": total}


# ---------------------------------------------------------------- orders


def _order(values, auto_submit):
    doc = frappe.get_doc({"doctype": ORDER, **values})
    doc.insert()
    if auto_submit:
        doc.submit()
    return doc.name


def _supplier_order(organization, bank_account, item, day, auto_submit):
    name = item.get("doc")
    if not name or not frappe.db.exists(RECEIPT, {"name": name, "organization": organization, "docstatus": 1}):
        return None, _("Документ {0} не знайдено або не проведений").format(name)
    receipt = frappe.get_doc(RECEIPT, name)
    receipt.check_permission("read")
    due = receipt_due(receipt)
    amount = flt(item.get("amount") if item.get("amount") not in (None, "") else due, 2)
    if amount <= 0 or amount > due:
        return None, _("Сума {0} більша за залишок до сплати {1}").format(uk_money(amount), uk_money(max(due, 0)))
    iban = default_iban(receipt.counterparty)
    if not iban:
        return None, _("У контрагента немає IBAN")
    party = frappe.db.get_value("UA Counterparty", receipt.counterparty, ["counterparty_name", "full_name", "edrpou"], as_dict=True)
    vat = round_money(amount * _vat_share(receipt))
    return _order(
        {
            "organization": organization, "posting_date": day, "bank_account": bank_account, "payment_kind": "Постачальнику",
            "counterparty": receipt.counterparty, "contract": receipt.contract,
            "recipient_name": party.full_name or party.counterparty_name, "recipient_iban": iban,
            "recipient_edrpou": party.edrpou, "amount": amount, "vat_amount": vat,
            "purpose": purpose_of(receipt.name, receipt.posting_date, vat), "basis_type": RECEIPT, "basis": receipt.name,
        },
        auto_submit,
    ), None


def _tax_order(organization, bank_account, item, day, auto_submit):
    tax_type = item.get("tax_type")
    horizon = max(0, date_diff(item.get("due_date"), day)) if item.get("due_date") else 0
    rows = tax_rows(organization, tax_type, day, horizon) if tax_type else []
    # the row of the period of the item; without a period the oldest one
    if item.get("period_end"):
        row = next((r for r in rows if r["period_end"] == str(item.get("period_end"))), None)
    else:
        row = rows[0] if rows else None
    if not row:
        return None, _("Немає суми до сплати за податком {0}").format(tax_type)
    amount = flt(item.get("amount") if item.get("amount") not in (None, "") else row["amount"], 2)
    if amount <= 0 or amount > row["amount"]:
        return None, _("Сума {0} більша за залишок до сплати {1}").format(uk_money(amount), uk_money(row["amount"]))
    account = tax_account(organization, tax_type)
    if not account:
        return None, _("Немає рахунку для сплати податку {0}").format(tax_type)
    edrpou = frappe.db.get_value("UA Organization", organization, "edrpou")
    return _order(
        {
            "organization": organization, "posting_date": day, "bank_account": bank_account, "payment_kind": "Податок",
            "recipient_name": account.recipient_name, "recipient_iban": account.iban,
            "recipient_edrpou": account.recipient_edrpou, "amount": amount, "purpose": f"*;101;{edrpou};{row['title']};;;",
            "tax_type": tax_type, "budget_code": account.budget_code,
        },
        auto_submit,
    ), None


def create_orders(organization, bank_account, items, date, auto_submit=0):
    day = getdate(date)
    if frappe.db.get_value("UA Bank Account", bank_account, "organization") != organization:
        frappe.throw(_("Банківський рахунок належить іншій організації"), frappe.ValidationError)
    created, skipped = [], []
    for item in _items(items):
        maker = _tax_order if item.get("kind") == "tax" else _supplier_order
        try:
            name, reason = maker(organization, bank_account, item, day, cint(auto_submit))
        except frappe.ValidationError as e:
            name, reason = None, frappe.as_unicode(e)
        if name:
            created.append(name)
        else:
            skipped.append({"item": item, "reason": reason})
    return {"created": created, "skipped": skipped}
