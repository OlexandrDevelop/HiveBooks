"""Fixed assets, intangible assets and low-value assets: state of an asset and monthly depreciation.

The state is not stored. Cost and wear are read from the accounting entries (accounts 10x/12x/112 and 13x
with the asset in the first subconto). Depreciation parameters come from the submitted acceptance.
Documents with their own posting are in ua_documents (UA Asset Acceptance, Depreciation, ...).
"""

import math

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, get_last_day, getdate

from ua_accounting.accounting.utils import first_of_month

FA = "UA Fixed Asset"
IA = "UA Intangible Asset"
LV = "UA Low Value Asset"
ASSET_TYPES = (FA, IA, LV)

ACCEPTANCE = "UA Asset Acceptance"
DEPRECIATION = "UA Asset Depreciation"
MODERNIZATION = "UA Asset Modernization"
TRANSFER = "UA Asset Transfer"
WRITEOFF = "UA Asset Writeoff"
SALE = "UA Asset Sale"
REVALUATION = "UA Asset Revaluation"
DISPOSALS = (WRITEOFF, SALE)
# documents of an asset after the acceptance
DEPENDENT = (MODERNIZATION, TRANSFER, WRITEOFF, SALE, REVALUATION)

SUBCONTO = {FA: "FixedAsset", IA: "IntangibleAsset", LV: "LowValueAsset"}
PURCHASE_ACCOUNT = {FA: "152", IA: "154", LV: "153"}
WEAR_ACCOUNT = {FA: "131", IA: "133", LV: "132"}
EXPENSE_PREFIXES = ("23", "91", "92", "93", "94")
DEFAULT_EXPENSE = "92"

STRAIGHT = "Прямолінійний"
DECLINING = "Зменшення залишкової вартості"
ACCELERATED = "Прискореного зменшення залишкової вартості"
CUMULATIVE = "Кумулятивний"
PRODUCTION = "Виробничий"
HALF = "50% + 50%"
FULL = "100%"
METHODS = (STRAIGHT, DECLINING, ACCELERATED, CUMULATIVE, PRODUCTION)
LOW_VALUE_METHODS = (HALF, FULL)

# account of the asset by the group (ПКУ 138.3.3) or the kind
_FA_ACCOUNT = {"1": "101", "2": "102", "3": "103", "4": "104", "5": "105", "6": "106", "7": "107", "8": "108"}
_IA_ACCOUNT = {"1": "121", "2": "122", "3": "123", "4": "124", "5": "125", "6": "127"}
# minimum useful life by the group, months (ПКУ 138.3.3)
_TAX_MONTHS = {"2": 180, "3": 240, "4": 60, "5": 60, "6": 48, "7": 72, "8": 120, "9": 144}


# ---------------------------------------------------------------- helpers


def month_gap(first, last):
    """Whole months from the month of `first` to the month of `last`."""
    return (last.year - first.year) * 12 + last.month - first.month


def group_number(value):
    return (value or "").split(".")[0].strip()


def default_account(asset_type, asset):
    if asset_type == LV:
        return "112"
    if asset_type == IA:
        kind = frappe.db.get_value(IA, asset, "asset_kind")
        return _IA_ACCOUNT.get(group_number(kind), "127")
    group = frappe.db.get_value(FA, asset, "asset_group")
    return _FA_ACCOUNT.get(group_number(group), "109")


def check_asset_account(asset_type, account):
    ok = {
        FA: len(account) == 3 and account.startswith("10"),
        IA: len(account) == 3 and account.startswith("12"),
        LV: account == "112",
    }[asset_type]
    if not ok:
        frappe.throw(_("Рахунок {0} не підходить для обліку цього виду активу").format(account))


def leaf_account(code):
    """Posting account for an expense group: 91 → 911, 94 → 940."""
    if frappe.db.get_value("UA Account", code, "is_group"):
        leaf = frappe.get_all(
            "UA Account", filters={"parent_ua_account": code, "is_group": 0}, pluck="name", order_by="name asc", limit=1
        )
        if leaf:
            return leaf[0]
    return code


def check_expense_account(code):
    if not code or not frappe.db.exists("UA Account", code) or not any(code.startswith(p) for p in EXPENSE_PREFIXES):
        frappe.throw(_("Рахунок витрат {0} має бути одним із 23, 91–94").format(code or ""))


# ---------------------------------------------------------------- state from documents and entries


def acceptances(organization, upto=None, asset_type=None, asset=None, exclude=None):
    """Submitted acceptance rows with the date and the document."""
    sql = [
        """select l.asset_type, l.asset, l.asset_account, l.initial_cost, l.liquidation_value, l.useful_life_months,
        l.depreciation_method, l.expected_output, l.expense_account, l.tax_useful_life_months,
        l.department, l.responsible,
        p.posting_date, p.name as document, p.organization
        from `tabUA Asset Acceptance Line` l join `tabUA Asset Acceptance` p on p.name = l.parent
        where p.docstatus = 1 and l.parenttype = 'UA Asset Acceptance'"""
    ]
    values = []
    for cond, value in (
        ("p.organization = %s", organization),
        ("p.posting_date <= %s", upto),
        ("l.asset_type = %s", asset_type),
        ("l.asset = %s", asset),
        ("p.name != %s", exclude),
    ):
        if value:
            sql.append("and " + cond)
            values.append(value)
    sql.append("order by p.posting_date, p.name, l.idx")
    return frappe.db.sql(" ".join(sql), values, as_dict=True)


def acceptance_of(asset_type, asset, organization=None, exclude=None):
    rows = acceptances(organization, None, asset_type, asset, exclude)
    return rows[0] if rows else None


def disposal_of(asset_type, asset, exclude=None):
    """(date, doctype, name) of the submitted write-off or sale of the asset, or None."""
    found = []
    for doctype in DISPOSALS:
        filters = {"asset_type": asset_type, "asset": asset, "docstatus": 1}
        if exclude and exclude[0] == doctype:
            filters["name"] = ("!=", exclude[1])
        for row in frappe.get_all(doctype, filters=filters, fields=["posting_date", "name"]):
            found.append((getdate(row.posting_date), doctype, row.name))
    return min(found) if found else None


def depreciated_since(asset_type, asset, date):
    """True when a submitted depreciation document dated on or after `date` has an amount of the asset."""
    return bool(
        frappe.db.sql(
            """select 1 from `tabUA Asset Depreciation Line` l join `tabUA Asset Depreciation` p on p.name = l.parent
            where p.docstatus = 1 and l.parenttype = 'UA Asset Depreciation' and l.asset_type = %s and l.asset = %s
            and l.amount > 0 and p.posting_date >= %s limit 1""",
            (asset_type, asset, getdate(date)),
        )
    )


def depreciated_in_month(asset_type, asset, date):
    """True when a submitted depreciation document of the month of `date` has an amount of the asset."""
    date = getdate(date)
    return bool(
        frappe.db.sql(
            """select 1 from `tabUA Asset Depreciation Line` l join `tabUA Asset Depreciation` p on p.name = l.parent
            where p.docstatus = 1 and l.parenttype = 'UA Asset Depreciation' and l.asset_type = %s and l.asset = %s
            and l.amount > 0 and p.posting_date between %s and %s limit 1""",
            (asset_type, asset, first_of_month(date), get_last_day(date)),
        )
    )


def has_dependents(asset_type, asset):
    if depreciated_since(asset_type, asset, "1900-01-01"):
        return True
    for doctype in DEPENDENT:
        if frappe.db.exists(doctype, {"asset_type": asset_type, "asset": asset, "docstatus": 1}):
            return True
    return False


def turnover(organization, account, asset, side, upto=None):
    """Debit ('dr') or credit ('cr') of an account for one asset (first subconto), up to the date inclusive."""
    sql = (
        f"select coalesce(sum(amount), 0) from `tabUA Accounting Entry` where organization = %s "
        f"and account_{side} = %s and subconto_{side}1 = %s"
    )
    values = [organization, account, asset]
    if upto:
        sql += " and posting_date <= %s"
        values.append(getdate(upto))
    return flt(frappe.db.sql(sql, values)[0][0], 2)


def cost_at(acc, upto=None):
    account = acc.asset_account
    return flt(turnover(acc.organization, account, acc.asset, "dr", upto) - turnover(acc.organization, account, acc.asset, "cr", upto), 2)


def wear_at(acc, upto=None):
    account = WEAR_ACCOUNT[acc.asset_type]
    return flt(turnover(acc.organization, account, acc.asset, "cr", upto) - turnover(acc.organization, account, acc.asset, "dr", upto), 2)


def tax_wear_before(asset_type, asset, first):
    return flt(
        frappe.db.sql(
            """select coalesce(sum(l.tax_amount), 0) from `tabUA Asset Depreciation Line` l
            join `tabUA Asset Depreciation` p on p.name = l.parent
            where p.docstatus = 1 and l.parenttype = 'UA Asset Depreciation' and l.asset_type = %s and l.asset = %s
            and p.posting_date < %s""",
            (asset_type, asset, first),
        )[0][0],
        2,
    )


def card_value(asset_type, asset, field):
    if frappe.get_meta(asset_type).has_field(field):
        return frappe.db.get_value(asset_type, asset, field)
    return None


def require_accepted(asset_type, asset, organization):
    """Acceptance of the asset in the organization, or an error."""
    if asset_type not in ASSET_TYPES:
        frappe.throw(_("Недопустимий вид активу {0}").format(asset_type))
    if not asset or not frappe.db.exists(asset_type, asset):
        frappe.throw(_("Актив {0} не знайдено").format(asset or ""))
    acc = acceptance_of(asset_type, asset, organization)
    if not acc:
        frappe.throw(_("Актив {0} не прийнято до обліку в цій організації").format(frappe.db.get_value(asset_type, asset, "asset_name")))
    return acc


# ---------------------------------------------------------------- depreciation


def end_month(acc, first):
    """First day of the last month of depreciation after the modernizations made before `first`."""
    start = add_months(first_of_month(acc.posting_date), 1)
    end = add_months(start, max(int(acc.useful_life_months or 0), 1) - 1)
    for row in frappe.get_all(
        MODERNIZATION,
        filters={
            "asset_type": acc.asset_type,
            "asset": acc.asset,
            "organization": acc.organization,
            "docstatus": 1,
            "posting_date": ("<", first),
            "new_useful_life_months": (">", 0),
        },
        fields=["posting_date", "new_useful_life_months"],
        order_by="posting_date asc, creation asc",
    ):
        end = add_months(first_of_month(row.posting_date), int(row.new_useful_life_months))
    return start, end


def tax_months(acc):
    """Tax useful life: not shorter than the minimum of the group (ПКУ 138.3.3)."""
    minimum = 0
    if acc.asset_type == FA:
        group = group_number(frappe.db.get_value(FA, acc.asset, "asset_group"))
        minimum = _TAX_MONTHS.get(group, 0)
    if acc.tax_useful_life_months:
        return max(int(acc.tax_useful_life_months), minimum)
    return minimum or int(acc.useful_life_months or 0)


def monthly_amounts(acc, month_end, quantity=0):
    """(accounting amount, tax amount) of the asset for the month that ends on `month_end`."""
    month_end = getdate(month_end)
    first = first_of_month(month_end)
    before = add_days(first, -1)
    method = acc.depreciation_method or STRAIGHT
    liquidation = 0.0 if acc.asset_type == LV else flt(acc.liquidation_value)

    if method in LOW_VALUE_METHODS:
        if first_of_month(acc.posting_date) != first:
            return 0.0, 0.0
        cost = cost_at(acc, month_end)
        if flt(wear_at(acc, before), 2) > 0:
            return 0.0, 0.0
        amount = flt(cost / 2, 2) if method == HALF else cost
        return amount, amount

    start, end = end_month(acc, first)
    if first < start:
        return 0.0, 0.0
    cost = cost_at(acc, before)
    wear = wear_at(acc, before)
    left = flt(cost - liquidation - wear, 2)
    amount = 0.0
    if left > 0:
        remaining = max(month_gap(first, end) + 1, 1)
        total_months = max(month_gap(start, end) + 1, 1)
        if method == PRODUCTION:
            expected = flt(acc.expected_output)
            amount = flt((cost - liquidation) * flt(quantity) / expected, 2) if expected > 0 else 0.0
        elif remaining == 1:
            amount = left
        elif method == DECLINING:
            years = total_months / 12
            floor = max(liquidation, 1.0)
            norm = 1 - (floor / cost) ** (1 / years) if cost > floor else 1.0
            ref = max(first.replace(month=1, day=1), start)
            residual = cost_at(acc, add_days(ref, -1)) - wear_at(acc, add_days(ref, -1))
            amount = flt(residual * norm / 12, 2)
        elif method in (ACCELERATED, CUMULATIVE):
            year = month_gap(start, first) // 12
            years = math.ceil(total_months / 12)
            if year >= years - 1 and method == ACCELERATED or year >= years:
                amount = flt(left / remaining, 2)
            elif method == ACCELERATED:
                ref = add_months(start, 12 * year)
                residual = cost_at(acc, add_days(ref, -1)) - wear_at(acc, add_days(ref, -1))
                norm = min(2.0 / (total_months / 12), 1.0)
                amount = flt(residual * norm / 12, 2)
            else:
                amount = flt((cost - liquidation) * (years - year) / (years * (years + 1) / 2) / 12, 2)
        else:
            amount = flt(left / remaining, 2)
        amount = min(amount, left)

    tax = amount
    if acc.asset_type != LV:
        tax_end = add_months(start, max(tax_months(acc), 1) - 1)
        tax_left = flt(cost - liquidation - tax_wear_before(acc.asset_type, acc.asset, first), 2)
        tax_remaining = month_gap(first, tax_end) + 1
        tax = 0.0
        if tax_left > 0:
            tax = flt(tax_left / max(tax_remaining, 1), 2)
    return amount, tax


def card_value_at(asset_type, asset, field, date=None, organization=None):
    """Department or responsible person on the date: the value of the acceptance, then every submitted
    transfer up to the date in the order of its date and name. No date: the latest state."""
    if field not in ("department", "responsible"):
        return card_value(asset_type, asset, field)
    new_field = f"new_{field}"
    filters = {"asset_type": asset_type, "asset": asset, "docstatus": 1, new_field: ("is", "set")}
    if date:
        filters["posting_date"] = ("<=", getdate(date))
    moves = frappe.get_all(
        TRANSFER, filters=filters, fields=[new_field], order_by="posting_date asc, name asc"
    )
    acc = acceptance_of(asset_type, asset, organization)
    # the acceptance keeps the place and the person at that time; the mutable card is used only without it
    value = acc.get(field) if acc else card_value(asset_type, asset, field)
    for move in moves:
        value = move.get(new_field)
    return value


def department_of(acc, date=None):
    return card_value_at(acc.asset_type, acc.asset, "department", date, acc.organization)


def depreciation_rows(organization, month_end, output=None):
    """Lines of the depreciation document of the organization for the month."""
    month_end = getdate(month_end)
    output = output or {}
    rows = []
    for acc in acceptances(organization, month_end):
        disposed = disposal_of(acc.asset_type, acc.asset)
        if disposed and disposed[0] <= month_end:
            continue
        amount, tax = monthly_amounts(acc, month_end, output.get((acc.asset_type, acc.asset), 0))
        if amount > 0 or tax > 0:
            rows.append(
                {
                    "asset_type": acc.asset_type,
                    "asset": acc.asset,
                    "amount": amount,
                    "tax_amount": tax,
                    "expense_account": acc.expense_account or DEFAULT_EXPENSE,
                    "department": department_of(acc, month_end),
                }
            )
    rows.sort(key=lambda r: (r["asset_type"], r["asset"]))
    return rows
