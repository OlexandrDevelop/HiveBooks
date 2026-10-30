"""Data of the home page "Головне". Read only; every read checks the user's permissions.

get_dashboard(organization)        -> balance cards and reminders
get_recent(organization, mode)     -> the newest documents (mode: all | mine | unposted)
"""

import frappe
from frappe.utils import add_months, cint, flt, get_first_day, getdate, nowdate

from ua_accounting.reporting.titles import Titles

DOCUMENTS = (
    "UA Sales Invoice",
    "UA Purchase Receipt",
    "UA Customer Order",
    "UA Supplier Order",
    "UA Cash Receipt",
    "UA Cash Payment",
    "UA Journal Operation",
)

# card -> account prefix and the side of the balance (dr: debit - credit, cr: credit - debit)
CARDS = (
    ("bank", "31", "dr"),
    ("cash", "30", "dr"),
    ("receivable", "36", "dr"),
    ("payable", "63", "cr"),
)

MONTHS = (
    "січень",
    "лютий",
    "березень",
    "квітень",
    "травень",
    "червень",
    "липень",
    "серпень",
    "вересень",
    "жовтень",
    "листопад",
    "грудень",
)


def _organization(organization):
    """The organization the user may read, or None (then nothing is filtered by it)."""
    if not organization:
        return None
    if not frappe.db.exists("UA Organization", organization):
        frappe.throw(frappe._("Організацію не знайдено"))
    frappe.has_permission("UA Organization", "read", doc=organization, throw=True)
    return organization


def _balance(prefix, side, organization, until):
    """Debit and credit of the accounts that start with prefix, up to the day (inclusive)."""
    where = ["posting_date <= %(until)s"]
    params = {"until": until, "prefix": prefix + "%"}
    if organization:
        where.append("organization = %(org)s")
        params["org"] = organization
    cond = " AND ".join(where)
    row = frappe.db.sql(
        f"""SELECT
            COALESCE(SUM(CASE WHEN account_dr LIKE %(prefix)s THEN amount ELSE 0 END), 0) AS dr,
            COALESCE(SUM(CASE WHEN account_cr LIKE %(prefix)s THEN amount ELSE 0 END), 0) AS cr
        FROM `tabUA Accounting Entry`
        WHERE {cond} AND (account_dr LIKE %(prefix)s OR account_cr LIKE %(prefix)s)""",
        params,
        as_dict=True,
    )[0]
    net = flt(row.dr) - flt(row.cr)
    return flt(net if side == "dr" else -net, 2)


def _readable(doctype):
    return frappe.has_permission(doctype, "read")


@frappe.whitelist()
def get_dashboard(organization=None):
    organization = _organization(organization)
    today = getdate(nowdate())
    month_start = get_first_day(today)
    out = {"today": str(today), "month_start": str(month_start), "cards": None, "reminders": []}

    if _readable("UA Accounting Entry"):
        cards = {}
        before = str(frappe.utils.add_days(month_start, -1))
        for key, prefix, side in CARDS:
            now_value = _balance(prefix, side, organization, str(today))
            start_value = _balance(prefix, side, organization, before)
            cards[key] = {"balance": now_value, "change": flt(now_value - start_value, 2)}
        out["cards"] = cards

    # documents that are not posted yet
    unposted = 0
    for doctype in DOCUMENTS:
        if not _readable(doctype):
            continue
        filters = {"docstatus": 0}
        if organization:
            filters["organization"] = organization
        unposted += frappe.db.count(doctype, filters)
    if unposted:
        out["reminders"].append({"kind": "unposted", "count": unposted})

    # VAT return: a month is reported by the 20th of the next month (Tax Code 49.18.1)
    vat_payer = cint(frappe.db.get_value("UA Organization", organization, "vat_payer")) if organization else 0
    if vat_payer:
        period = add_months(today, -1) if today.day <= 20 else today
        due = getdate(add_months(get_first_day(period), 1)).replace(day=20)
        out["reminders"].append(
            {
                "kind": "vat",
                "month": MONTHS[period.month - 1],
                "year": period.year,
                "due": str(due),
                "days": (due - today).days,
            }
        )
    out["period"] = {"month": MONTHS[today.month - 1], "year": today.year}
    return out


@frappe.whitelist()
def get_recent(organization=None, mode="all", limit=7):
    organization = _organization(organization)
    limit = min(max(cint(limit) or 7, 1), 20)
    rows = []
    for doctype in DOCUMENTS:
        if not _readable(doctype):
            continue
        meta = frappe.get_meta(doctype)
        fields = ["name", "posting_date", "docstatus", "modified", "owner"]
        for f in ("counterparty", "total_amount", "amount", "currency"):
            if meta.has_field(f):
                fields.append(f)
        filters = {"docstatus": ("<", 2)} if mode != "unposted" else {"docstatus": 0}
        if organization:
            filters["organization"] = organization
        if mode == "mine":
            filters["owner"] = frappe.session.user
        for r in frappe.get_list(doctype, fields=fields, filters=filters, order_by="modified desc", limit=limit):
            r["doctype"] = doctype
            rows.append(r)
    rows.sort(key=lambda r: r.modified, reverse=True)
    rows = rows[:limit]
    titles = Titles()
    titles.preload(("UA Counterparty", r.get("counterparty")) for r in rows)
    return [
        {
            "doctype": r.doctype,
            "name": r.name,
            "posting_date": str(r.posting_date) if r.posting_date else "",
            "docstatus": r.docstatus,
            "counterparty": titles.get("UA Counterparty", r.get("counterparty")) if r.get("counterparty") else "",
            "amount": flt(r.get("total_amount") if r.get("total_amount") is not None else r.get("amount")),
            "currency": r.get("currency") or "",
        }
        for r in rows
    ]
