"""Filters shared by all reports.

Browser and API send one JSON object. Common keys:
    date_from, date_to   period (both days included)
    organizations        list of UA Organization names (empty = all)
    accounts             list of UA Account names (groups are opened)
    currency             UA Currency name
    subconto             [{"type": "Counterparty", "values": ["CP-1", ...]}, ...]
Every other key is kept in `opts` for the report itself.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate

COMMON = ("date_from", "date_to", "organizations", "accounts", "currency", "subconto")


def as_list(value, keep_empty=False):
    """List from a list, a JSON list or a comma separated string."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            value = frappe.parse_json(text)
        else:
            value = [v.strip() for v in text.split(",")]
    if not isinstance(value, (list, tuple)):
        value = [value]
    out = []
    for v in value:
        v = "" if v is None else str(v).strip()
        if v or keep_empty:
            out.append(v)
    return out


def parse_subconto(value):
    """[{"type", "values"}] -> list; one item per type, empty items dropped."""
    if isinstance(value, str):
        value = frappe.parse_json(value) if value.strip() else []
    by_type = {}
    for item in value or []:
        stype = (item.get("type") or "").strip()
        values = as_list(item.get("values", item.get("value")), keep_empty=True)
        # an explicit [""] means "value is not set"; an empty list means no filter
        if stype and values:
            by_type[stype] = values
    return [{"type": t, "values": v} for t, v in by_type.items()]


class Filters:
    def __init__(self, date_from, date_to, organizations, accounts, currency, subconto, opts):
        self.date_from = date_from
        self.date_to = date_to
        # first day after the period: ranges are [date_from, end)
        self.end = add_days(date_to, 1)
        self.organizations = organizations
        self.accounts = accounts
        self.currency = currency
        self.subconto = subconto
        self.opts = opts

    def flag(self, key, default=0):
        value = self.opts.get(key, default)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes")
        return bool(value)

    def number(self, key, default=0):
        try:
            return int(self.opts.get(key, default) or 0)
        except (TypeError, ValueError):
            return default


def parse_filters(raw):
    data = frappe.parse_json(raw) if isinstance(raw, str) else dict(raw or {})
    if not data.get("date_from") or not data.get("date_to"):
        frappe.throw(_("Вкажіть період звіту"))
    date_from = getdate(data["date_from"])
    date_to = getdate(data["date_to"])
    if date_from > date_to:
        frappe.throw(_("Початок періоду пізніше за його кінець"))

    accounts = as_list(data.get("accounts"))
    if not accounts and data.get("account"):
        accounts = as_list(data.get("account"))

    return Filters(
        date_from=date_from,
        date_to=date_to,
        organizations=as_list(data.get("organizations")),
        accounts=accounts,
        currency=(data.get("currency") or "").strip(),
        subconto=parse_subconto(data.get("subconto")),
        opts={k: v for k, v in data.items() if k not in COMMON},
    )
