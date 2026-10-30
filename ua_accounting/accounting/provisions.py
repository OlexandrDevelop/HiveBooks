"""Provisions: reserve of doubtful debts (38), vacation reserve (471), warranty provision (473).

The calculations read the accounting register (UA Accounting Entry) and the documents.
Posting is done by the documents UA Provision Accrual, UA Bad Debt Write-off
and UA Vacation Reserve Inventory.
"""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, get_last_day, getdate

from ua_accounting.accounting.utils import first_of_month

SETTINGS = "UA Provision Settings"

M_CLASS = "За класифікацією боргів"
M_COEF = "За коефіцієнтом сумнівності"
M_ABS = "За абсолютною сумою сумнівної заборгованості"
METHODS = (M_CLASS, M_COEF, M_ABS)

KIND_DOUBTFUL = "Резерв сумнівних боргів"
KIND_VACATION = "Резерв відпусток"
KIND_WARRANTY = "Забезпечення гарантійних зобов'язань"

RESERVE_ACCOUNT = "38"
VACATION_ACCOUNT = "471"
WARRANTY_ACCOUNT = "473"
EXPENSE_ACCOUNT = "944"
SALES_EXPENSE_ACCOUNT = "93"
INCOME_ACCOUNT = "719"
RECEIVABLE_PREFIX = "36"
# cost accounts that wages are charged to
COST_ACCOUNTS_SQL = "(account_dr = '23' or account_dr like '9%%')"


def round_money(value):
    """Round half up to kopecks."""
    return float(Decimal(str(flt(value, 9))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_settings(organization):
    if not organization or not frappe.db.exists(SETTINGS, organization):
        return None
    return frappe.get_doc(SETTINGS, organization)


def credit_balance(organization, account, date):
    """Credit minus debit of an account up to the end of `date`."""
    debit = frappe.db.sql(
        "select coalesce(sum(amount), 0) from `tabUA Accounting Entry` "
        "where organization = %s and account_dr = %s and posting_date <= %s",
        (organization, account, getdate(date)),
    )[0][0]
    credit = frappe.db.sql(
        "select coalesce(sum(amount), 0) from `tabUA Accounting Entry` "
        "where organization = %s and account_cr = %s and posting_date <= %s",
        (organization, account, getdate(date)),
    )[0][0]
    return flt(flt(credit) - flt(debit), 2)


def split(organization, account, date, amount):
    """(part covered by the provision, rest to expense) for a payment of `amount`."""
    amount = flt(amount, 2)
    covered = max(0.0, min(amount, credit_balance(organization, account, date)))
    return flt(covered, 2), flt(amount - covered, 2)


# ---------------------------------------------------------------- doubtful debts


def receivables(organization, date, counterparty=None, contract=None, settlement_doc=None):
    """Debt of customers per settlement document at the end of `date`.

    Rows: {account, counterparty, contract, settlement_doc, doc_type, debt, currency, currency_amount}.
    `settlement_doc` None means any document; "" means the debt without a document.
    """
    date = getdate(date)
    debts = {}
    for side, sign in (("dr", 1), ("cr", -1)):
        rows = frappe.db.sql(
            f"""select account_{side} as account, subconto_{side}1 as counterparty, subconto_{side}2 as contract,
            subconto_{side}3 as doc, subconto_{side}3_type as doc_type, currency_{side} as currency,
            sum(amount) as amount, sum(currency_amount_{side}) as currency_amount
            from `tabUA Accounting Entry`
            where organization = %s and account_{side} like %s and posting_date <= %s
            and subconto_{side}1 != ''
            group by 1, 2, 3, 4, 5, 6""",
            (organization, RECEIVABLE_PREFIX + "%", date),
            as_dict=True,
        )
        for r in rows:
            key = (r.account, r.counterparty, r.contract, r.doc_type, r.doc)
            item = debts.setdefault(key, {"debt": 0.0, "currency": "", "currency_amount": 0.0})
            item["debt"] += sign * flt(r.amount)
            item["currency"] = item["currency"] or r.currency or ""
            item["currency_amount"] += sign * flt(r.currency_amount)
    result = []
    for (account, cp, ct, doc_type, doc), item in debts.items():
        debt = flt(item["debt"], 2)
        if debt <= 0:
            continue
        if (
            (counterparty and cp != counterparty)
            or (contract and ct != contract)
            or (settlement_doc is not None and doc != settlement_doc)
        ):
            continue
        result.append(
            {
                "account": account, "counterparty": cp, "contract": ct, "settlement_doc": doc, "doc_type": doc_type,
                "debt": debt, "currency": item["currency"], "currency_amount": flt(item["currency_amount"], 2),
            }
        )
    return result


def settlement_date(doc_type, doc, organization, counterparty=None, contract=None):
    """Posting date of a settlement document (first debit entry of the receivable if the document has no date).

    A debt without a settlement document (an opening balance, a revaluation) is dated by its first debit entry.
    """
    if not doc:
        value = frappe.db.sql(
            "select min(posting_date) from `tabUA Accounting Entry` where organization = %s and account_dr like %s "
            "and subconto_dr1 = %s and subconto_dr2 = %s and subconto_dr3 = ''",
            (organization, RECEIVABLE_PREFIX + "%", counterparty or "", contract or ""),
        )[0][0]
        return getdate(value) if value else None
    if doc_type and frappe.db.exists("DocType", doc_type) and frappe.get_meta(doc_type).has_field("posting_date"):
        value = frappe.db.get_value(doc_type, doc, "posting_date")
        if value:
            return getdate(value)
    value = frappe.db.sql(
        "select min(posting_date) from `tabUA Accounting Entry` where organization = %s and account_dr like %s "
        "and subconto_dr3 = %s",
        (organization, RECEIVABLE_PREFIX + "%", doc),
    )[0][0]
    return getdate(value) if value else None


def class_percent(settings, overdue_days):
    for row in settings.classes if settings else []:
        low = row.days_from or 0
        # an empty upper limit is stored as 0: it means "no limit" unless the range starts at 0
        open_end = not row.days_to and low > 0
        if overdue_days >= low and (open_end or overdue_days <= (row.days_to or 0)):
            return flt(row.percent)
    return 0.0


def calculate_doubtful(organization, date, method=None):
    date = getdate(date)
    settings = get_settings(organization)
    method = method or (settings.doubtful_method if settings else None) or M_CLASS
    if method not in METHODS:
        frappe.throw(_("Невідомий метод резерву сумнівних боргів: {0}").format(method), frappe.ValidationError)
    marked = {}
    if method == M_ABS and settings:
        for row in settings.doubtful_debts:
            key = (row.counterparty, row.contract, row.settlement_doc or "")
            marked[key] = marked.get(key, 0.0) + flt(row.doubtful_amount)
    terms = {}
    rows = []
    for d in sorted(receivables(organization, date), key=lambda x: (x["settlement_doc"])):
        contract = d["contract"]
        if contract not in terms:
            terms[contract] = frappe.db.get_value("UA Counterparty Contract", contract, "payment_days") or 0
        posted = settlement_date(d["doc_type"], d["settlement_doc"], organization, d["counterparty"], contract)
        overdue = 0
        if posted:
            overdue = max(0, (date - add_days(posted, terms[contract])).days)
        if method == M_CLASS:
            percent = class_percent(settings, overdue)
            reserve = round_money(d["debt"] * percent / 100)
        elif method == M_COEF:
            percent = flt(settings.doubtful_coefficient) if settings else 0.0
            reserve = round_money(d["debt"] * percent / 100)
        else:
            key = (d["counterparty"], contract, d["settlement_doc"] or "")
            if marked.get(key, 0) <= 0:
                continue
            reserve = round_money(min(marked[key], d["debt"]))
            marked[key] = flt(marked[key] - reserve, 2)
            percent = flt(reserve / d["debt"] * 100, 2)
        rows.append(
            {
                "counterparty": d["counterparty"],
                "contract": contract,
                "settlement_doc": d["settlement_doc"],
                "debt": d["debt"],
                "overdue_days": overdue,
                "percent": percent,
                "reserve": reserve,
            }
        )
    return {"method": method, "total": round_money(sum(r["reserve"] for r in rows)), "rows": rows}


# ---------------------------------------------------------------- vacation reserve


def vacation_coefficient(settings):
    """Planned vacation pay / planned wage fund, in percent."""
    if not settings or not flt(settings.planned_wage_fund_year):
        return 0.0
    return flt(flt(settings.planned_vacation_pay_year) / flt(settings.planned_wage_fund_year) * 100, 6)


def calculate_vacation(organization, period):
    start = first_of_month(period)
    end = get_last_day(start)
    settings = get_settings(organization)
    coefficient = vacation_coefficient(settings)
    rows = frappe.db.sql(
        f"""select account_dr as account, subconto_dr1 as expense_item, subconto_dr2 as department, sum(amount) as base
        from `tabUA Accounting Entry`
        where organization = %s and posting_date between %s and %s and account_cr in ('661', '651')
        and {COST_ACCOUNTS_SQL}
        group by account_dr, subconto_dr1, subconto_dr2 order by account_dr, subconto_dr1, subconto_dr2""",
        (organization, start, end),
        as_dict=True,
    )
    result = []
    for r in rows:
        base = flt(r.base, 2)
        amount = round_money(base * coefficient / 100)
        result.append(
            {
                "expense_account": r.account,
                "expense_item": r.expense_item or (settings.expense_item if settings else None),
                "department": r.department or (settings.department if settings else None),
                "base": base,
                "amount": amount,
            }
        )
    return {
        "coefficient": flt(coefficient, 4),
        "base": flt(sum(r["base"] for r in result), 2),
        "amount": round_money(sum(r["amount"] for r in result)),
        "rows": result,
    }


def required_vacation_reserve(days, daily_pay, esv_rate):
    return round_money(flt(days) * flt(daily_pay) * (1 + flt(esv_rate) / 100))


# ---------------------------------------------------------------- warranty


def warranty_lines(organization, start, end):
    """Net sales (UAH) of the items with a warranty in a period: [(item, sale date, net)]. Returns are deducted."""
    result = []
    for doctype, sign in (("UA Sales Invoice", 1), ("UA Sales Return", -1)):
        rows = frappe.db.sql(
            f"""select l.item, d.posting_date, (l.total - l.vat_amount) * coalesce(nullif(d.exchange_rate, 0), 1) as net
            from `tab{doctype}` d join `tabUA Goods Line` l on l.parent = d.name and l.parenttype = %s
            where d.organization = %s and d.docstatus = 1 and d.posting_date between %s and %s
            and coalesce((select warranty_percent from `tabUA Item` i where i.name = l.item), 0) > 0""",
            (doctype, organization, start, end),
            as_dict=True,
        )
        result.extend((r.item, getdate(r.posting_date), sign * flt(r.net)) for r in rows)
    return result


def calculate_warranty(organization, period):
    start = first_of_month(period)
    end = get_last_day(start)
    base = {}
    for item, _date, net in warranty_lines(organization, start, end):
        base[item] = base.get(item, 0.0) + net
    rows = []
    for item in sorted(base):
        percent = flt(frappe.db.get_value("UA Item", item, "warranty_percent"))
        amount = round_money(base[item] * percent / 100)
        if amount:
            rows.append({"item": item, "base_amount": flt(base[item], 2), "percent": percent, "amount": amount})
    return {"total": round_money(sum(r["amount"] for r in rows)), "rows": rows}


def warranty_expiring(organization, period):
    """Provision accrued for sales whose warranty period ends in the month `period`."""
    start = first_of_month(period)
    total = 0.0
    rows = frappe.db.sql(
        """select i.name, i.warranty_percent, i.warranty_months from `tabUA Item` i
        where coalesce(i.warranty_percent, 0) > 0 and coalesce(i.warranty_months, 0) > 0""",
        as_dict=True,
    )
    for item in rows:
        # sales made `warranty_months` before the month: their warranty ends in this month
        sold_from = add_months(start, -item.warranty_months)
        sold_to = get_last_day(sold_from)
        net = sum(n for it, _d, n in warranty_lines(organization, sold_from, sold_to) if it == item.name)
        total += round_money(net * flt(item.warranty_percent) / 100)
    return round_money(total)


# ---------------------------------------------------------------- closing steps


def accrual_values(organization, kind, period_end):
    """Rows and amounts of a provision accrual for the month ending `period_end`, or (None, message)."""
    settings = get_settings(organization)
    if not settings:
        return None, _("Не заповнено налаштування резервів організації")
    period = first_of_month(period_end)
    if kind == KIND_DOUBTFUL:
        result = calculate_doubtful(organization, period_end, settings.doubtful_method)
        if not result["rows"]:
            if credit_balance(organization, RESERVE_ACCOUNT, period_end) <= 0:
                return None, _("Немає дебіторської заборгованості покупців")
            # no debts left: the old reserve is reversed
        rows = [
            {
                "counterparty": r["counterparty"], "contract": r["contract"], "settlement_doc": r["settlement_doc"],
                "base_amount": r["debt"], "overdue_days": r["overdue_days"], "percent": r["percent"],
                "amount": r["reserve"],
            }
            for r in result["rows"]
        ]
        return {"rows": rows, "required": result["total"]}, None
    if kind == KIND_VACATION:
        result = calculate_vacation(organization, period)
        rows = [
            {
                "base_amount": r["base"], "percent": result["coefficient"], "amount": r["amount"],
                "expense_account": r["expense_account"], "expense_item": r["expense_item"], "department": r["department"],
            }
            for r in result["rows"]
            if r["amount"]
        ]
        if not rows:
            return None, _("Немає нарахованої заробітної плати або планових показників")
        return {"rows": rows, "required": result["amount"]}, None
    result = calculate_warranty(organization, period)
    rows = [dict(r) for r in result["rows"]]
    expiring = warranty_expiring(organization, period)
    reverse = min(expiring, max(0.0, credit_balance(organization, WARRANTY_ACCOUNT, period_end)))
    if reverse:
        rows.append({"base_amount": expiring, "amount": -round_money(reverse)})
    if not rows:
        return None, _("Немає продажів товарів із гарантією")
    return {"rows": rows, "required": flt(result["total"] - reverse, 2)}, None


def run_provision_step(organization, kind, period_end):
    """Closing step: create and submit a UA Provision Accrual. Returns (document name or None, message)."""
    values, message = accrual_values(organization, kind, period_end)
    if not values:
        return None, message
    doc = frappe.get_doc(
        {
            "doctype": "UA Provision Accrual",
            "organization": organization,
            "posting_date": getdate(period_end),
            "kind": kind,
            "rows": values["rows"],
        }
    )
    doc.insert()
    if not flt(doc.delta):
        doc.delete()
        return None, _("Резерв не змінився")
    doc.submit()
    return doc.name, _("Проведено {0}").format(doc.name)
