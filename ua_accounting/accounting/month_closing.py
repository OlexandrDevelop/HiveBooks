"""Month-end closing (1C «Закриття місяця»): routine operations in a fixed order.

Every step builds the rows of one UA Journal Operation dated the last day of the month and posts it
through the ledger. A step without data is done and has no document. Re-run and cancel go in the
reverse order of the steps. Completing all steps sets the period lock of the organization.
"""

import contextlib
import importlib.util
import math
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.utils import add_days, add_months, get_last_day, getdate

from ua_accounting.accounting import ledger
from ua_accounting.accounting.assets import leaf_account, month_gap
from ua_accounting.accounting.utils import first_of_month, uk_date, uk_money

CLOSING = "UA Month Closing"
OP = "UA Journal Operation"
PROVISION = "UA Provision Accrual"

TODO, DONE, ERROR, PARTLY = "Не виконано", "Виконано", "Помилка", "Частково"

PROFIT_TAX_RATE = 18  # ПКУ ст.136
VAT_SMALL_SHARE = 5  # ПКУ ст.198.5
DEFAULT_EXPENSE = "92"
REVALUATION_ITEM = "Курсові різниці"

# (code, name); the order is the order of execution
STEPS = [
    ("depreciation", "Нарахування амортизації"),
    ("revaluation", "Переоцінка валютних коштів і розрахунків"),
    ("vat_distribution", "Розподіл ПДВ"),
    ("provision_doubtful_debts", "Резерв сумнівних боргів"),
    ("provision_vacation", "Резерв відпусток"),
    ("provision_warranty", "Забезпечення гарантійних зобов'язань"),
    ("close_23_91", "Закриття рахунків 23, 91"),
    ("close_92_94", "Списання витрат 92, 93, 94 на фінансовий результат"),
    ("profit_tax", "Розрахунок податку на прибуток"),
    ("close_income_expense", "Закриття рахунків доходів і витрат"),
    ("financial_result", "Визначення фінансового результату"),
]
STEP_NAMES = dict(STEPS)
# T-452: the provision module posts its own document
PROVISION_KINDS = {
    "provision_doubtful_debts": "KIND_DOUBTFUL",
    "provision_vacation": "KIND_VACATION",
    "provision_warranty": "KIND_WARRANTY",
}
# documents of these steps only move amounts between the result accounts
TRANSFER_STEPS = ("close_92_94", "close_income_expense", "financial_result")


def money(value):
    """Round to kopecks, half up."""
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@contextlib.contextmanager
def closing_context():
    """The posting documents of the closing are not blocked by the period lock."""
    old = frappe.flags.get("ua_month_closing")
    frappe.flags.ua_month_closing = True
    try:
        yield
    finally:
        frappe.flags.ua_month_closing = old


# ---------------------------------------------------------------- ledger reading


def leaf_accounts(*prefixes, currency=False):
    filters = {"is_group": 0}
    if currency:
        filters["currency_accounting"] = 1
    names = frappe.get_all("UA Account", filters=filters, pluck="name")
    return sorted(n for n in names if n.startswith(prefixes))


def balances(organization, upto, accounts):
    """Balance of every (account, subconto, currency) up to the date inclusive.

    Returns dicts: account, subs [(type, value) x 3], currency, amount (Дт − Кт), cur_amount (Дт − Кт).
    """
    if not accounts:
        return []
    sides = []
    for side, sign_d, sign_c in (("dr", "amount", "0"), ("cr", "0", "amount")):
        cur = f"currency_amount_{side}"
        sides.append(
            f"""select account_{side} as account,
            subconto_{side}1_type as t1, subconto_{side}1 as s1, subconto_{side}2_type as t2, subconto_{side}2 as s2,
            subconto_{side}3_type as t3, subconto_{side}3 as s3, currency_{side} as cur,
            {sign_d} as d, {sign_c} as c,
            {cur if side == "dr" else "0"} as cd, {cur if side == "cr" else "0"} as cc
            from `tabUA Accounting Entry`
            where organization = %(org)s and posting_date <= %(upto)s and account_{side} in %(accounts)s"""
        )
    rows = frappe.db.sql(
        f"""select account, t1, s1, t2, s2, t3, s3, cur, sum(d) - sum(c) as amount, sum(cd) - sum(cc) as cur_amount
        from ({" union all ".join(sides)}) x group by account, t1, s1, t2, s2, t3, s3, cur
        order by account, s1, s2, s3""",
        {"org": organization, "upto": getdate(upto), "accounts": tuple(accounts)},
        as_dict=True,
    )
    return [
        {
            "account": r.account,
            "subs": [(r.t1 or "", r.s1 or ""), (r.t2 or "", r.s2 or ""), (r.t3 or "", r.s3 or "")],
            "currency": r.cur or "",
            "amount": money(r.amount),
            "cur_amount": float(r.cur_amount or 0),
        }
        for r in rows
    ]


def rate_on(currency, date):
    """Rate of one unit in hryvnias, the latest rate on or before the date (0 if none)."""
    from ua_accounting.ua_catalogs.doctype.ua_currency.ua_currency import rate_row

    row = rate_row(currency, date)
    if not row:
        return 0.0
    return float(row.rate or 0) / (row.multiplicity or 1)


def sum_entries(sql, values):
    return money(frappe.db.sql(sql, values)[0][0])


# ---------------------------------------------------------------- journal rows


def sub_fields(side, subs):
    out = {}
    for i, (kind, value) in enumerate(subs or [], start=1):
        if value:
            out[f"subconto_{side}{i}_type"] = kind
            out[f"subconto_{side}{i}"] = value
    return out


def typed_subs(account, ctx, **by_type):
    """Subconto slots of an account from {subconto type: (doctype, value)}; types the account lacks are dropped."""
    acc = ledger._account(account, ctx)
    slots = []
    for meta in acc.subconto[:3]:
        slots.append(by_type.get(meta.subconto_type) or ("", ""))
    return slots


def entry(dr, cr, amount, dr_sub=None, cr_sub=None, content="", **extra):
    row = {"account_dr": dr, "account_cr": cr, "amount": money(amount), "content": content}
    row.update(sub_fields("dr", dr_sub))
    row.update(sub_fields("cr", cr_sub))
    row.update(extra)
    return row


def move(balance, result_account, content=""):
    """Close one balance to the result account: debit balance → Дт result Кт account, credit → the opposite."""
    amount = balance["amount"]
    if not amount:
        return None
    if amount > 0:
        return entry(result_account, balance["account"], amount, cr_sub=balance["subs"], content=content)
    return entry(balance["account"], result_account, -amount, dr_sub=balance["subs"], content=content)


def close_accounts(organization, end, accounts, target, content):
    rows = []
    for b in balances(organization, end, accounts):
        row = move(b, target(b["account"]), content)
        if row:
            rows.append(row)
    return rows


# ---------------------------------------------------------------- steps: each returns (rows, message)


def step_depreciation(organization, end):
    """Straight-line and the other card methods, per asset. The first accrual is in the month after commissioning."""
    first = first_of_month(end)
    costs = defaultdict(float)
    for b in balances(organization, end, leaf_accounts("10")):
        if b["subs"][0][0] == "UA Fixed Asset":
            costs[b["subs"][0][1]] += b["amount"]
    wear = defaultdict(float)
    for b in balances(organization, add_days(first, -1), ["131"]):
        if b["subs"][0][0] == "UA Fixed Asset":
            wear[b["subs"][0][1]] -= b["amount"]
    ctx = {}
    rows, skipped = [], 0
    assets = frappe.get_all(
        "UA Fixed Asset",
        filters={"organization": organization},
        fields=[
            "name", "commissioning_date", "useful_life_months", "depreciation_method", "residual_value",
            "expense_account", "expense_item", "department",
        ],
        order_by="name asc",
    )
    for a in assets:
        life = int(a.useful_life_months or 0)
        cost = money(costs.get(a.name))
        if not a.commissioning_date or life <= 0 or cost <= 0:
            continue
        start = first_of_month(add_months(first_of_month(a.commissioning_date), 1))
        if first < start:
            continue
        left = money(cost - (a.residual_value or 0) - wear.get(a.name, 0))
        if left <= 0:
            continue
        index = month_gap(start, first)
        base = cost - (a.residual_value or 0)
        method = a.depreciation_method or "Прямолінійний"
        if index >= life - 1:
            amount = left
        elif method == "Виробничий":
            skipped += 1
            continue
        elif method in ("Зменшення залишкової вартості", "Прискореного зменшення залишкової вартості"):
            amount = money((cost - wear.get(a.name, 0)) * 2 / life)
        elif method == "Кумулятивний":
            years = math.ceil(life / 12)
            amount = money(base * (years - index // 12) / (years * (years + 1) / 2) / 12)
        else:
            amount = money(base / life)
        amount = min(amount, left)
        if amount <= 0:
            continue
        account = leaf_account(a.expense_account or DEFAULT_EXPENSE)
        dr_sub = typed_subs(
            account,
            ctx,
            ExpenseItem=("UA Expense Item", a.expense_item) if a.expense_item else None,
            Department=("UA Department", a.department) if a.department else None,
        )
        cr_sub = [("UA Fixed Asset", a.name), ("", ""), ("", "")]
        rows.append(entry(account, "131", amount, dr_sub, cr_sub, _("Нарахування амортизації")))
    note = _("Виробничий метод пропущено: немає обсягу випуску") if skipped else ""
    return rows, note


def expense_item_for_rates():
    name = frappe.db.get_value("UA Expense Item", {"item_name": REVALUATION_ITEM})
    if name:
        return name
    doc = frappe.new_doc("UA Expense Item")
    doc.item_name = REVALUATION_ITEM
    doc.insert(ignore_permissions=True)
    return doc.name


def step_revaluation(organization, end):
    """Monetary items in a foreign currency at the rate of the last day (НП(С)БО 21): Дт item Кт 714 / Дт 945 Кт item."""
    accounts = leaf_accounts("30", "31", "36", "37", "63", "68", currency=True)
    rows, rates, ctx = [], {}, {}
    for b in balances(organization, end, accounts):
        currency = b["currency"]
        if not currency:
            continue
        if currency not in rates:
            rates[currency] = rate_on(currency, end)
            if frappe.db.get_value("UA Currency", currency, "is_base"):
                rates[currency] = 1.0
        rate = rates[currency]
        if not rate:
            if b["amount"] or b["cur_amount"]:
                frappe.throw(_("Немає курсу валюти {0} на {1}").format(currency, uk_date(end)))
            continue
        diff = money(b["cur_amount"] * rate - b["amount"])
        if not diff:
            continue
        if diff > 0:
            rows.append(
                entry(b["account"], "714", diff, b["subs"], None, _("Курсова різниця"),
                      currency_dr=currency, currency_amount_dr=0)
            )
        else:
            item = expense_item_for_rates()
            dr_sub = typed_subs("945", ctx, ExpenseItem=("UA Expense Item", item))
            rows.append(
                entry("945", b["account"], -diff, dr_sub, b["subs"], _("Курсова різниця"),
                      currency_cr=currency, currency_amount_cr=0)
            )
    return rows, ""


def vat_shares(organization, first, end):
    """(taxable, exempt) net supplies of the month from the revenue accounts with the VAT rate subconto."""
    totals = defaultdict(float)
    for side, sign in (("cr", 1), ("dr", -1)):
        for rate, amount in frappe.db.sql(
            f"""select subconto_{side}2, sum(amount) from `tabUA Accounting Entry`
            where organization = %s and posting_date between %s and %s and account_{side} like %s
            and subconto_{side}2_type = 'UA VAT Rate' group by subconto_{side}2""",
            (organization, first, end, "70%"),
        ):
            totals[rate] += sign * float(amount or 0)
    taxable = exempt = 0.0
    for rate, amount in totals.items():
        if frappe.db.get_value("UA VAT Rate", rate, "is_taxable"):
            taxable += amount
        else:
            exempt += amount
    return money(taxable), money(exempt)


def step_vat_distribution(organization, end):
    """ПКУ ст.198.5: with more than 5 % of supplies not taxed, that share of the input VAT of expenses is not credit.

    The share is returned from the VAT credit to the cost account: Дт cost account Кт 644. VAT of stock purchases
    stays in the credit (its part would go to the cost of the goods, which the app does not recalculate).
    """
    first = first_of_month(end)
    taxable, exempt = vat_shares(organization, first, end)
    total = taxable + exempt
    if total <= 0 or exempt * 100 / total <= VAT_SMALL_SHARE:
        return [], _("Частка операцій, що не оподатковуються, не більша за {0} %: ПДВ не розподіляється").format(VAT_SMALL_SHARE)
    share = exempt / total
    rows, ctx = [], {}
    credits = frappe.db.sql(
        """select registrar_type, registrar, sum(vat_amount) as vat from `tabUA VAT Credit Entry`
        where organization = %s and posting_date between %s and %s group by registrar_type, registrar
        order by registrar_type, registrar""",
        (organization, first, end),
        as_dict=True,
    )
    for credit in credits:
        lines = frappe.db.sql(
            """select account_dr, subconto_dr1_type as t1, subconto_dr1 as s1, subconto_dr2_type as t2,
            subconto_dr2 as s2, subconto_dr3_type as t3, subconto_dr3 as s3, sum(amount) as amount
            from `tabUA Accounting Entry` where registrar_type = %s and registrar = %s and organization = %s
            and account_cr like '63%%' and account_dr not like '644%%'
            group by account_dr, t1, s1, t2, s2, t3, s3 order by account_dr, s1, s2, s3""",
            (credit.registrar_type, credit.registrar, organization),
            as_dict=True,
        )
        net = sum(float(x.amount) for x in lines)
        expense = [x for x in lines if x.account_dr.startswith(("23", "91", "92", "93", "94"))]
        expense_net = sum(float(x.amount) for x in expense)
        if not net or not expense_net:
            continue
        part = money(float(credit.vat) * expense_net / net * share)
        left = part
        for i, x in enumerate(expense):
            amount = left if i == len(expense) - 1 else money(part * float(x.amount) / expense_net)
            left = money(left - amount)
            if amount <= 0:
                continue
            subs = [(x.t1 or "", x.s1 or ""), (x.t2 or "", x.s2 or ""), (x.t3 or "", x.s3 or "")]
            rows.append(
                entry(x.account_dr, "644", amount, subs, typed_subs("644", ctx, TaxType=("UA Tax Type", "VAT")),
                      _("Розподіл ПДВ"))
            )
    return rows, ""


def step_close_23_91(organization, end):
    """Overheads 911/912 to 23, 913 to the cost of sales, 23 to the cost of services (the app has no output document)."""
    content = _("Закриття рахунків 23, 91")
    rows = []
    on_23 = defaultdict(float)
    keys = {}
    for b in balances(organization, end, ["23"]):
        key = tuple(b["subs"])
        keys[key] = b["subs"]
        on_23[key] += b["amount"]
    for b in balances(organization, end, ["911", "912"]):
        amount = b["amount"]
        if not amount:
            continue
        key = tuple(b["subs"])
        keys[key] = b["subs"]
        on_23[key] += amount
        if amount > 0:
            rows.append(entry("23", b["account"], amount, b["subs"], b["subs"], content))
        else:
            rows.append(entry(b["account"], "23", -amount, b["subs"], b["subs"], content))
    for b in balances(organization, end, ["913"]):
        row = move(b, "903", content)
        if row:
            rows.append(row)
    for key, amount in on_23.items():
        amount = money(amount)
        if amount > 0:
            rows.append(entry("903", "23", amount, None, keys[key], content))
        elif amount < 0:
            rows.append(entry("23", "903", -amount, keys[key], None, content))
    return rows, ""


def step_close_92_94(organization, end):
    return close_accounts(organization, end, leaf_accounts("92", "93", "94"), lambda a: "791",
                          _("Списання витрат на фінансовий результат")), ""


def accounting_profit(organization, first_day, end, exclude):
    """Credit minus debit of the income and expense accounts (70–76, 90–97) of the period, without the closing transfers."""
    accounts = tuple(
        a for a in leaf_accounts("7", "90", "91", "92", "93", "94", "95", "96", "97") if not a.startswith("79")
    )
    if not accounts:
        return 0.0
    skip = tuple(exclude) or ("",)
    total = 0.0
    for side, sign in (("cr", 1), ("dr", -1)):
        value = frappe.db.sql(
            f"""select coalesce(sum(amount), 0) from `tabUA Accounting Entry`
            where organization = %(org)s and posting_date between %(first)s and %(end)s
            and account_{side} in %(accounts)s and not (registrar_type = 'UA Journal Operation' and registrar in %(skip)s)""",
            {"org": organization, "first": first_day, "end": end, "accounts": accounts, "skip": skip},
        )[0][0]
        total += sign * float(value or 0)
    return money(total)


def transfer_documents(organization):
    return frappe.db.sql_list(
        """select s.document from `tabUA Month Closing Step` s join `tabUA Month Closing` c on c.name = s.parent
        where c.organization = %s and s.step in %s and ifnull(s.document, '') != ''""",
        (organization, TRANSFER_STEPS),
    )


def step_profit_tax(organization, end):
    """18 % of the accounting profit since 1 January minus the tax accrued in the year (account 98)."""
    end = getdate(end)
    year_start = end.replace(month=1, day=1)
    skip = transfer_documents(organization)
    profit = accounting_profit(organization, year_start, end, skip)
    target = money(profit * PROFIT_TAX_RATE / 100) if profit > 0 else 0.0
    accrued = 0.0
    accounts = tuple(leaf_accounts("98"))
    for side, sign in (("dr", 1), ("cr", -1)):
        value = frappe.db.sql(
            f"""select coalesce(sum(amount), 0) from `tabUA Accounting Entry`
            where organization = %(org)s and posting_date between %(first)s and %(end)s
            and account_{side} in %(accounts)s and not (registrar_type = 'UA Journal Operation' and registrar in %(skip)s)""",
            {"org": organization, "first": year_start, "end": end, "accounts": accounts or ("",), "skip": tuple(skip) or ("",)},
        )[0][0]
        accrued += sign * float(value or 0)
    delta = money(target - accrued)
    ctx = {}
    tax_sub = typed_subs("641", ctx, TaxType=("UA Tax Type", "CIT"))
    content = _("Податок на прибуток")
    message = _("Прибуток з початку року {0}, податок {1}, нараховано раніше {2}").format(
        uk_money(profit), uk_money(target), uk_money(accrued)
    )
    if delta > 0:
        return [entry("981", "641", delta, None, tax_sub, content)], message
    if delta < 0:
        return [entry("641", "981", -delta, tax_sub, None, content)], message
    return [], message


RESULT_ACCOUNT = [
    (("70", "71", "90"), "791"),
    (("72", "73", "95", "96"), "792"),
    (("74", "97", "98"), "793"),
    (("75", "76", "99"), "794"),
]


def result_account(account):
    for prefixes, target in RESULT_ACCOUNT:
        if account.startswith(prefixes):
            return target
    return "793"


def step_close_income_expense(organization, end):
    accounts = [a for a in leaf_accounts("7", "90", "95", "96", "97", "98", "99") if not a.startswith("79")]
    return close_accounts(organization, end, accounts, result_account, _("Закриття доходів і витрат")), ""


def step_financial_result(organization, end):
    """79 → 44: the profit of a sub-account Дт 79x Кт 441, the loss Дт 442 Кт 79x."""
    rows = []
    content = _("Фінансовий результат")
    for b in balances(organization, end, leaf_accounts("79")):
        if b["amount"] < 0:
            rows.append(entry(b["account"], "441", -b["amount"], b["subs"], None, content))
        elif b["amount"] > 0:
            rows.append(entry("442", b["account"], b["amount"], None, b["subs"], content))
    return rows, ""


RUNNERS = {
    "depreciation": step_depreciation,
    "revaluation": step_revaluation,
    "vat_distribution": step_vat_distribution,
    "close_23_91": step_close_23_91,
    "close_92_94": step_close_92_94,
    "profit_tax": step_profit_tax,
    "close_income_expense": step_close_income_expense,
    "financial_result": step_financial_result,
}


# ---------------------------------------------------------------- running

STEP_FIELDS = ("step", "step_name", "status", "document_type", "document", "message", "idx")


def new_steps():
    return [{"step": code, "step_name": name, "status": TODO} for code, name in STEPS]


def post_operation(closing, row_name, rows):
    doc = frappe.new_doc(OP)
    doc.organization = closing.organization
    doc.posting_date = closing.period_end
    doc.content = f"{_('Закриття місяця')}: {row_name}"
    for r in rows:
        doc.append("entries", r)
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc.name


def run_provision(closing, code):
    if not importlib.util.find_spec("ua_accounting.accounting.provisions"):
        return None, _("Резерви не підключено")
    from ua_accounting.accounting import provisions

    document, message = provisions.run_provision_step(
        closing.organization, getattr(provisions, PROVISION_KINDS[code]), getdate(closing.period_end)
    )
    return document, message


def execute(closing, row):
    """Run one step: post its document and fill the row. An error rolls back the step and marks it."""
    code = row.step
    savepoint = f"closing_{code}"
    frappe.db.savepoint(savepoint)
    try:
        document_type = document = None
        if code in PROVISION_KINDS:
            document, message = run_provision(closing, code)
            document_type = PROVISION if document else None
        else:
            rows, note = RUNNERS[code](closing.organization, closing.period_end)
            if rows:
                document, document_type = post_operation(closing, row.step_name, rows), OP
                total = money(sum(r["amount"] for r in rows))
                message = _("Проведено проводок: {0} на суму {1} грн").format(len(rows), uk_money(total))
                if note:
                    message = f"{message}. {note}"
            else:
                message = note or _("Немає даних для проведення")
        row.status, row.document_type, row.document, row.message = DONE, document_type, document, message
        save(closing)  # later steps read the documents of the earlier ones from the step table
        return True
    except Exception as e:
        frappe.db.rollback(save_point=savepoint)
        frappe.clear_messages()
        row.status, row.document_type, row.document = ERROR, None, None
        row.message = (str(e) or e.__class__.__name__)[:500]
        if not isinstance(e, frappe.ValidationError | frappe.PermissionError):
            frappe.log_error(f"Month closing {closing.name} {code}")
        save(closing)
        return False


def save(closing):
    closing.flags.ignore_permissions = True
    closing.save()


def cancel_row(row):
    """Cancel the document of a step and reset the row."""
    if row.document and row.document_type and frappe.db.exists(row.document_type, row.document):
        doc = frappe.get_doc(row.document_type, row.document)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
    row.status, row.document_type, row.document, row.message = TODO, None, None, None


def set_lock(closing):
    """All steps done: the lock date is the end of the month (never earlier than an existing one).
    Any step not done: the lock date set by the closing goes back to the previous value."""
    org = closing.organization
    end = getdate(closing.period_end)
    current = frappe.db.get_value("UA Organization", org, "edit_lock_date")
    if closing.status == DONE and closing.lock_after_closing and not closing.lock_applied:
        closing.previous_lock_date = current
        closing.lock_applied = 1
        frappe.db.set_value("UA Organization", org, "edit_lock_date", max(end, getdate(current)) if current else end)
    elif closing.status != DONE and closing.lock_applied:
        applied = max(end, getdate(closing.previous_lock_date)) if closing.previous_lock_date else end
        if current and getdate(current) == applied:
            frappe.db.set_value("UA Organization", org, "edit_lock_date", closing.previous_lock_date)
        closing.lock_applied = 0


def finish(closing):
    states = {r.status for r in closing.steps}
    closing.status = DONE if states == {DONE} else PARTLY if DONE in states else TODO
    set_lock(closing)
    save(closing)
    return state(closing)


def state(closing):
    return {
        "name": closing.name,
        "organization": closing.organization,
        "period": str(closing.period),
        "period_end": str(closing.period_end),
        "status": closing.status,
        "lock_after_closing": closing.lock_after_closing,
        "edit_lock_date": str(frappe.db.get_value("UA Organization", closing.organization, "edit_lock_date") or ""),
        "steps": [{k: (r.get(k) or "") for k in STEP_FIELDS} for r in closing.steps],
    }


def load(name):
    """The closing locked for update, with the permission of the caller checked."""
    frappe.only_for(("UA Accountant", "UA Accounting Manager", "UA Chief Accountant", "System Manager"))
    if not frappe.db.exists(CLOSING, name):
        frappe.throw(_("Закриття місяця {0} не знайдено").format(name), frappe.DoesNotExistError)
    frappe.db.sql("select name from `tabUA Month Closing` where name = %s for update", name)
    closing = frappe.get_doc(CLOSING, name)
    closing.check_permission("write")
    return closing


def find_row(closing, code):
    for i, row in enumerate(closing.steps):
        if row.step == code:
            return i, row
    frappe.throw(_("Невідома операція закриття: {0}").format(code))


def open_closing(organization, period):
    """The closing of the month, created when it does not exist yet."""
    frappe.only_for(("UA Accountant", "UA Accounting Manager", "UA Chief Accountant", "System Manager"))
    frappe.has_permission(CLOSING, "read", throw=True)
    first = first_of_month(period)
    name = frappe.db.get_value(CLOSING, {"organization": organization, "period": first})
    if not name:
        doc = frappe.new_doc(CLOSING)
        doc.organization, doc.period = organization, first
        try:
            doc.insert()
            name = doc.name
        except frappe.DuplicateEntryError:
            # another request created the closing first
            name = frappe.db.get_value(CLOSING, {"closing_key": f"{organization}|{first}"})
            if not name:
                raise
    closing = frappe.get_doc(CLOSING, name)
    closing.check_permission("read")
    return state(closing)


def run_step(name, code):
    closing = load(name)
    index, row = find_row(closing, code)
    for earlier in closing.steps[:index]:
        if earlier.status != DONE:
            frappe.throw(_("Спочатку виконайте операцію «{0}»").format(earlier.step_name))
    with closing_context():
        for later in reversed(closing.steps[index:]):
            if later.status != TODO or later.document:
                cancel_row(later)
        execute(closing, row)
        return finish(closing)


def run_all(name):
    closing = load(name)
    with closing_context():
        for row in reversed(closing.steps):
            if row.status != TODO or row.document:
                cancel_row(row)
        for row in closing.steps:
            if not execute(closing, row):
                break
        return finish(closing)


def cancel_step(name, code):
    closing = load(name)
    index, row = find_row(closing, code)
    if row.status != DONE:
        frappe.throw(_("Операція «{0}» не виконана").format(row.step_name))
    for later in closing.steps[index + 1 :]:
        if later.status == DONE:
            frappe.throw(_("Спочатку скасуйте операцію «{0}»").format(later.step_name))
    with closing_context():
        cancel_row(row)
        return finish(closing)


def cancel_all(name):
    closing = load(name)
    with closing_context():
        for row in reversed(closing.steps):
            if row.status != TODO or row.document:
                cancel_row(row)
        return finish(closing)


def guard_cancel(doc, method=None):
    """A document of a closing step is cancelled only from the closing."""
    if doc.doctype not in (OP, PROVISION) or frappe.flags.get("ua_month_closing"):
        return
    step = frappe.db.get_value(
        "UA Month Closing Step", {"document_type": doc.doctype, "document": doc.name, "status": DONE}, "step_name"
    )
    if step:
        frappe.throw(_("Документ створено операцією «{0}» закриття місяця. Скасуйте її у закритті місяця").format(step))
