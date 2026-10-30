"""Settlement reports: accountable persons (372), founders (671), budget (641, 642, 651) and loans."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import settlements

MONEY = {"fieldtype": "Currency", "width": 130}
ACCOUNTABLE = "372"
FOUNDERS = "671"
BUDGET_ACCOUNTS = ("641", "642", "651")
ESV_ACCOUNT = "651"  # has no tax type subconto: all of it is ЄСВ
CASH_ACCOUNTS = ("30%", "31%")


def check_access(organization, doctype):
    if not organization:
        frappe.throw(_("Вкажіть організацію"))
    frappe.has_permission(doctype, "read", throw=True)
    frappe.has_permission("UA Organization", "read", organization, throw=True)


def side_sums(organization, account, side, date_from, date_to, counter=None, counter_not=None):
    """{subconto 1: [sum before date_from, sum in the period]} of one side of an account.

    `counter`: LIKE patterns of the other account to take; `counter_not`: exact accounts to leave out.
    """
    other = "cr" if side == "dr" else "dr"
    sql = f"""select subconto_{side}1 sub_key, coalesce(sum(case when posting_date < %s then amount end), 0) before_sum,
        coalesce(sum(case when posting_date >= %s then amount end), 0) turn_sum
        from `tabUA Accounting Entry` where organization = %s and account_{side} = %s and posting_date <= %s"""
    values = [date_from, date_from, organization, account, date_to]
    if counter:
        sql += " and (" + " or ".join([f"account_{other} like %s"] * len(counter)) + ")"
        values += list(counter)
    if counter_not:
        sql += f" and account_{other} not in ({', '.join(['%s'] * len(counter_not))})"
        values += list(counter_not)
    sql += f" group by subconto_{side}1"
    return {r[0] or "": [flt(r[1], 2), flt(r[2], 2)] for r in frappe.db.sql(sql, values)}


def merge(*sources):
    """Rows of the keys of all sources: each key has the list of its [before, turn] pairs."""
    keys = sorted(set().union(*sources))
    return {k: [s.get(k, [0.0, 0.0]) for s in sources] for k in keys}


# ---------------------------------------------------------------- accountable persons


def accountable_columns():
    return [
        {"fieldname": "person", "label": _("Підзвітна особа"), "fieldtype": "Link", "options": "UA Person", "width": 240},
        {"fieldname": "opening", "label": _("Сальдо на початок"), **MONEY},
        {"fieldname": "debit", "label": _("Видано"), **MONEY},
        {"fieldname": "credit", "label": _("Витрачено за звітами"), **MONEY},
        {"fieldname": "closing", "label": _("Сальдо на кінець"), **MONEY},
    ]


def accountable_rows(filters):
    check_access(filters.organization, "UA Advance Report")
    args = (filters.organization, ACCOUNTABLE)
    span = (getdate(filters.date_from), getdate(filters.date_to))
    dr = side_sums(*args, "dr", *span)
    cr = side_sums(*args, "cr", *span)
    rows = []
    for person, ((dr_before, debit), (cr_before, credit)) in merge(dr, cr).items():
        if filters.person and person != filters.person:
            continue
        opening = flt(dr_before - cr_before, 2)
        closing = flt(opening + debit - credit, 2)
        if any((opening, debit, credit, closing)):
            rows.append({"person": person, "opening": opening, "debit": debit, "credit": credit, "closing": closing})
    return rows


# ---------------------------------------------------------------- founders


def founder_columns():
    return [
        {"fieldname": "person", "label": _("Засновник"), "fieldtype": "Link", "options": "UA Person", "width": 240},
        {"fieldname": "dividends_accrued", "label": _("Нараховано дивідендів"), **MONEY},
        {"fieldname": "taxes_withheld", "label": _("Утримано податків"), **MONEY},
        {"fieldname": "paid", "label": _("Виплачено"), **MONEY},
        {"fieldname": "to_pay", "label": _("До виплати"), **MONEY},
    ]


def founder_rows(filters):
    check_access(filters.organization, "UA Dividend Accrual")
    args = (filters.organization, FOUNDERS)
    span = (getdate(filters.date_from), getdate(filters.date_to))
    accrued = side_sums(*args, "cr", *span, counter=("443",))
    taxes = side_sums(*args, "dr", *span, counter=("641", "642"))
    paid = side_sums(*args, "dr", *span, counter=CASH_ACCOUNTS)
    debit = side_sums(*args, "dr", *span)
    credit = side_sums(*args, "cr", *span)
    rows = []
    for person, (acc, tax, pay, dr, cr) in merge(accrued, taxes, paid, debit, credit).items():
        if filters.person and person != filters.person:
            continue
        to_pay = flt(cr[0] + cr[1] - dr[0] - dr[1], 2)
        row = {"person": person, "dividends_accrued": acc[1], "taxes_withheld": tax[1], "paid": pay[1], "to_pay": to_pay}
        if any(row[k] for k in row if k != "person"):
            rows.append(row)
    return rows


# ---------------------------------------------------------------- budget


def budget_columns():
    return [
        {"fieldname": "tax_type", "label": _("Податок"), "fieldtype": "Link", "options": "UA Tax Type", "width": 240},
        {"fieldname": "opening", "label": _("Борг на початок"), **MONEY},
        {"fieldname": "accrued", "label": _("Нараховано"), **MONEY},
        {"fieldname": "paid", "label": _("Сплачено"), **MONEY},
        {"fieldname": "closing", "label": _("Борг на кінець"), **MONEY},
    ]


def budget_rows(filters):
    check_access(filters.organization, "UA Tax Payment")
    span = (getdate(filters.date_from), getdate(filters.date_to))
    totals = {}
    for account in BUDGET_ACCOUNTS:
        for side in ("dr", "cr"):
            for key, (before, turn) in side_sums(filters.organization, account, side, *span).items():
                tax_type = settlements.TAX_ESV if account == ESV_ACCOUNT else key
                row = totals.setdefault(tax_type, [0.0, 0.0, 0.0, 0.0])
                sign = 1 if side == "cr" else -1
                row[0] += sign * before
                row[1 if side == "cr" else 2] += turn
    rows = []
    for tax_type in sorted(totals):
        opening, accrued, paid, _unused = totals[tax_type]
        closing = flt(opening + accrued - paid, 2)
        row = {"tax_type": tax_type, "opening": flt(opening, 2), "accrued": flt(accrued, 2), "paid": flt(paid, 2),
               "closing": closing}
        if any(row[k] for k in row if k != "tax_type"):
            rows.append(row)
    return rows


# ---------------------------------------------------------------- loans


def loan_columns():
    return [
        {"fieldname": "loan", "label": _("Кредит / позика"), "fieldtype": "Link", "options": "UA Loan", "width": 280},
        {"fieldname": "principal_balance", "label": _("Залишок основної суми"), **MONEY},
        {"fieldname": "interest_accrued", "label": _("Нараховано відсотків"), **MONEY},
        {"fieldname": "interest_paid", "label": _("Сплачено відсотків"), **MONEY},
        {"fieldname": "interest_due", "label": _("Борг за відсотками"), **MONEY},
    ]


def loan_rows(filters):
    check_access(filters.organization, "UA Loan")
    until = getdate(filters.date_to) if filters.date_to else None
    rows = []
    for loan in frappe.get_all("UA Loan", filters={"organization": filters.organization}, pluck="name",
                               order_by="start_date asc, creation asc"):
        accrued = settlements.interest_accrued(loan, until)
        paid = settlements.interest_paid(loan, until)
        rows.append({"loan": loan, "principal_balance": settlements.principal_balance(loan, until),
                     "interest_accrued": accrued, "interest_paid": paid, "interest_due": flt(accrued - paid, 2)})
    return rows
