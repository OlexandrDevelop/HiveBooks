"""Manager monitor: key financial figures of an organization from the accounting register."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.utils import title_of

TOP = 10


def _balances(organization, prefixes, day, group):
    """Debit minus credit of accounts by prefix up to the day, grouped by account and the first subconto.

    `group` is the list of columns of the result besides the account.
    """
    result = {}
    for side, sign in (("dr", 1), ("cr", -1)):
        like = " or ".join(f"account_{side} like %s" for _p in prefixes)
        rows = frappe.db.sql(
            f"""select account_{side} as account, subconto_{side}1 as sub, sum(amount) as amount
            from `tabUA Accounting Entry` where organization = %s and posting_date <= %s and ({like}) group by 1, 2""",
            (organization, day, *[p + "%" for p in prefixes]),
            as_dict=True,
        )
        for r in rows:
            key = (r.account, r.sub)
            result[key] = result.get(key, 0.0) + sign * flt(r.amount)
    return result


def _money(organization, day):
    parts = {"cash": 0.0, "bank": 0.0}
    for (account, _sub), balance in _balances(organization, ("30", "31"), day, None).items():
        if balance > 0:
            parts["cash" if account.startswith("30") else "bank"] += balance
    cash, bank = flt(parts["cash"], 2), flt(parts["bank"], 2)
    return {"cash": cash, "bank": bank, "total": flt(cash + bank, 2)}


def _debts(organization, account, day, sign):
    """Positive balances of an account by counterparty: {total, top}."""
    by_party = {}
    for (_account, party), balance in _balances(organization, (account,), day, None).items():
        by_party[party] = by_party.get(party, 0.0) + sign * balance
    rows = sorted(
        ((p, flt(v, 2)) for p, v in by_party.items() if p and flt(v, 2) > 0), key=lambda x: (-x[1], x[0])
    )
    return {
        "total": flt(sum(v for _p, v in rows), 2),
        "top": [{"counterparty": p, "amount": v} for p, v in rows[:TOP]],
    }


def _turnover(organization, prefix_pattern, date_from, date_to, side):
    return flt(
        frappe.db.sql(
            f"""select coalesce(sum(amount), 0) from `tabUA Accounting Entry` where organization = %s
            and posting_date between %s and %s and account_{side} regexp %s""",
            (organization, date_from, date_to, prefix_pattern),
        )[0][0]
    )


def _net_income(organization, pattern, date_from, date_to):
    return flt(
        _turnover(organization, pattern, date_from, date_to, "cr") - _turnover(organization, pattern, date_from, date_to, "dr"), 2
    )


def _sales_by_month(organization, date_from, date_to):
    months = {}
    for side, sign in (("cr", 1), ("dr", -1)):
        rows = frappe.db.sql(
            f"""select date_format(posting_date, '%%Y-%%m') as month, sum(amount) as amount
            from `tabUA Accounting Entry` where organization = %s and posting_date between %s and %s
            and account_{side} like '70%%' group by 1""",
            (organization, date_from, date_to),
            as_dict=True,
        )
        for r in rows:
            months[r.month] = months.get(r.month, 0.0) + sign * flt(r.amount)
    return [{"month": m, "amount": flt(v, 2)} for m, v in sorted(months.items()) if flt(v, 2)]


def get_widgets(organization, date_from, date_to):
    date_from, date_to = getdate(date_from), getdate(date_to)
    if date_from > date_to:
        frappe.throw(_("Початок періоду пізніше за кінець"), frappe.ValidationError)
    if not frappe.db.exists("UA Organization", organization):
        frappe.throw(_("Організацію {0} не знайдено").format(organization), frappe.ValidationError)
    by_month = _sales_by_month(organization, date_from, date_to)
    income = _net_income(organization, "^7", date_from, date_to)
    expenses = flt(
        _turnover(organization, "^9[0-7]", date_from, date_to, "dr") - _turnover(organization, "^9[0-7]", date_from, date_to, "cr"), 2
    )
    receivable = _debts(organization, "361", date_to, 1)
    payable = _debts(organization, "631", date_to, -1)
    parties = {r["counterparty"] for r in receivable["top"] + payable["top"]}
    return {
        "money": _money(organization, date_to),
        "receivable": receivable,
        "payable": payable,
        "sales": {"total": flt(sum(m["amount"] for m in by_month), 2), "by_month": by_month},
        "profit": {"income": income, "expenses": expenses, "profit": flt(income - expenses, 2)},
        "titles": {p: title_of("UA Counterparty", p) for p in parties},
    }
