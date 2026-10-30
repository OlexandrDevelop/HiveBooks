"""Balances and validation shared by bank and cash documents."""

import frappe
from frappe import _
from frappe.utils import flt


def account_balance(organization, account, date, subconto_type=None, subconto=None, before=False,
                    with_empty=False, in_currency=False):
    """Balance from dated ledger entries, optionally for one analytic value.

    with_empty also counts entries posted without any value of that analytic.
    in_currency sums the foreign-currency quantity instead of the UAH amount."""
    condition = "<" if before else "<="
    result = 0
    for side, sign in (("dr", 1), ("cr", -1)):
        sql = (f"select coalesce(sum({'currency_amount_' + side if in_currency else 'amount'}), 0) from `tabUA Accounting Entry` "
               f"where organization=%s and account_{side}=%s and posting_date {condition} %s")
        params = [organization, account, date]
        if subconto_type:
            slots = frappe.get_all("UA Account Subconto", filters={"parent": account},
                                   fields=["subconto_type"], order_by="idx asc")
            names = [row.subconto_type for row in slots]
            if subconto_type not in names:
                return 0
            column = f"subconto_{side}{names.index(subconto_type) + 1}"
            if with_empty:
                sql += f" and ({column}=%s or {column} is null or {column}='')"
            else:
                sql += f" and {column}=%s"
            params.append(subconto)
        result += sign * frappe.db.sql(sql, params)[0][0]
    return flt(result, 2)


def has_currency_entries(organization, account, date, subconto_type, subconto):
    """True when any entry of the analytic value carries a foreign-currency quantity."""
    names = frappe.get_all("UA Account Subconto", filters={"parent": account},
                           fields=["subconto_type"], order_by="idx asc", pluck="subconto_type")
    if subconto_type not in names:
        return False
    slot = names.index(subconto_type) + 1
    return bool(frappe.db.sql(
        f"""select 1 from `tabUA Accounting Entry` where organization=%s and posting_date <= %s and
        ((account_dr=%s and subconto_dr{slot}=%s and currency_amount_dr != 0) or
         (account_cr=%s and subconto_cr{slot}=%s and currency_amount_cr != 0)) limit 1""",
        (organization, date, account, subconto, account, subconto)))


def desk_balance(organization, cash_desk, date, before=False):
    """Cash balance of one desk.

    Like in 1C, the only UAH desk of the organization also owns the entries posted without a desk.
    """
    desks = frappe.get_all("UA Cash Desk", filters={"organization": organization}, fields=["name", "currency"])
    uah = [row.name for row in desks if (row.currency or "UAH") == "UAH"]
    own = uah == [cash_desk]
    return account_balance(organization, "301", date, "CashDesk", cash_desk, before=before, with_empty=own)


def check_cash_balance(organization, cash_desk, date, change, check_limit=True):
    """Check the balance on this and subsequent posting dates for the desk.

    A cancel only lowers or raises the balance, so it checks the negative balance (check_limit=False)."""
    if not cash_desk:
        return
    limit = flt(frappe.db.get_value("UA Cash Desk", cash_desk, "cash_limit"))
    dates = [date] + frappe.db.sql_list(
        """select distinct posting_date from `tabUA Accounting Entry`
        where organization=%s and posting_date>%s and
        (account_dr='301' or account_cr='301') order by posting_date""",
        (organization, date),
    )
    for day in dates:
        balance = flt(desk_balance(organization, cash_desk, day) + change, 2)
        if balance < 0:
            frappe.throw(_("Недостатньо коштів: від'ємний залишок каси"))
        if check_limit and limit and balance > limit:
            frappe.throw(_("Перевищено ліміт залишку каси"))
