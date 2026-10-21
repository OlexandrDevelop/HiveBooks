"""Posting API of the accounting register.

Documents call:
    post_entries(doc, entries)    from on_submit
    cancel_entries(doc)           from on_cancel
    repost_entries(doc, entries)  cancel + post in one transaction

The module never commits. It runs in the transaction of the caller.
Only MariaDB is supported (INSERT ... ON DUPLICATE KEY UPDATE).
"""

import hashlib

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import vat
from ua_accounting.accounting.utils import first_of_month, pick, std_columns

ENTRY = "UA Accounting Entry"
TURNOVER = "UA Account Turnover"
SIDES = ("dr", "cr")
SLOTS = (1, 2, 3)

ENTRY_FIELDS = [
    "posting_date",
    "period",
    "registrar_type",
    "registrar",
    "line_no",
    "organization",
    "account_dr",
    "account_cr",
    *[f"subconto_{s}{i}_type" for s in SIDES for i in SLOTS],
    *[f"subconto_{s}{i}" for s in SIDES for i in SLOTS],
    "amount",
    "quantity_dr",
    "quantity_cr",
    "currency_dr",
    "currency_cr",
    "currency_amount_dr",
    "currency_amount_cr",
    "content",
]

# numeric columns of the totals table, changed by every posting
TURNOVER_SUMS = ("debit", "credit", "quantity_dr", "quantity_cr", "currency_dr", "currency_cr")


# ---------------------------------------------------------------- public API


def post_entries(doc, entries):
    """Write entries of the registrar `doc` and add them to the monthly totals."""
    entries = list(entries or [])
    if not entries:
        return
    ctx = {}
    rows = [_build_row(doc, e, idx, ctx) for idx, e in enumerate(entries, start=1)]

    values = []
    std = std_columns()
    for row in rows:
        values.append([row[f] for f in ENTRY_FIELDS] + [std[k] for k in std])
    frappe.db.bulk_insert(ENTRY, ENTRY_FIELDS + list(std), values)

    deltas = {}
    for row in rows:
        _add_deltas(deltas, row, ctx, 1)
    _apply_deltas(deltas)


def cancel_entries(doc):
    """Delete entries of the registrar and take them out of the totals."""
    filters = {"registrar_type": doc.doctype, "registrar": doc.name}
    rows = frappe.get_all(ENTRY, filters=filters, fields=["*"], limit_page_length=0)
    if rows:
        ctx = {}
        deltas = {}
        for row in rows:
            _add_deltas(deltas, row, ctx, -1)
        _apply_deltas(deltas)
        frappe.db.delete(ENTRY, filters)
        _delete_empty_totals(list(deltas))
    vat.cancel_vat_entries(doc)


def repost_entries(doc, entries):
    cancel_entries(doc)
    post_entries(doc, entries)


@frappe.whitelist(methods=["POST"])
def rebuild_totals(organization=None, from_period=None):
    """Recompute the totals table from entries. For repair and checks.

    Without filters all totals are rebuilt. Manager only.
    """
    frappe.only_for(("UA Accounting Manager", "System Manager"))
    filters = {}
    if organization:
        filters["organization"] = organization
    if from_period:
        filters["period"] = (">=", first_of_month(from_period))
    frappe.db.delete(TURNOVER, filters)

    ctx = {}
    deltas = {}
    last_name = 0
    while True:
        batch = frappe.get_all(
            ENTRY,
            filters={**filters, "name": (">", last_name)},
            fields=["*"],
            order_by="name asc",
            limit_page_length=10000,
        )
        if not batch:
            break
        for row in batch:
            _add_deltas(deltas, row, ctx, 1)
        last_name = batch[-1].name
    _apply_deltas(deltas)
    return len(deltas)


# ---------------------------------------------------------------- internals


def _account(name, ctx):
    """Account settings, cached in `ctx` for one call."""
    if name in ctx:
        return ctx[name]
    acc = frappe.db.get_value(
        "UA Account",
        name,
        ["is_group", "off_balance", "currency_accounting", "quantity_accounting"],
        as_dict=True,
    )
    if not acc:
        frappe.throw(_("Рахунок {0} не знайдено").format(name))
    acc.subconto = frappe.db.sql(
        """select s.subconto_type, s.turnover_only, t.reference_doctype, t.is_dynamic
        from `tabUA Account Subconto` s
        left join `tabUA Subconto Type` t on t.name = s.subconto_type
        where s.parent = %s and s.parenttype = 'UA Account'
        order by s.idx""",
        name,
        as_dict=True,
    )
    ctx[name] = acc
    return acc


def _map_subconto(account, acc, values):
    """Map {subconto type: value} to 3 slots of (doctype, value)."""
    slots = [("", "")] * len(SLOTS)
    types = [s.subconto_type for s in acc.subconto]
    for key, value in (values or {}).items():
        if key not in types:
            frappe.throw(
                _("Рахунок {0} не має субконто {1}").format(account, key),
                exc=frappe.ValidationError,
            )
        pos = types.index(key)
        meta = acc.subconto[pos]
        if not value:
            continue
        if meta.is_dynamic:
            if not (isinstance(value, (tuple, list)) and len(value) == 2):
                frappe.throw(_("Субконто {0}: потрібна пара (DocType, назва)").format(key))
            slots[pos] = (value[0], value[1])
        else:
            slots[pos] = (meta.reference_doctype or "", value)
    return slots


def _build_row(doc, e, idx, ctx):
    posting_date = pick(doc, e, "posting_date")
    organization = pick(doc, e, "organization")
    if not posting_date or not organization:
        frappe.throw(_("Проводка {0}: потрібні дата та організація").format(idx))
    posting_date = getdate(posting_date)
    if not frappe.db.exists("UA Organization", organization):
        frappe.throw(_("Організацію {0} не знайдено").format(organization))

    account_dr = e.get("account_dr") or ""
    account_cr = e.get("account_cr") or ""
    if not account_dr and not account_cr:
        frappe.throw(_("Проводка {0}: не вказано рахунки").format(idx))

    row = {
        "posting_date": posting_date,
        "period": first_of_month(posting_date),
        "registrar_type": doc.doctype,
        "registrar": doc.name,
        "line_no": idx,
        "organization": organization,
        "account_dr": account_dr,
        "account_cr": account_cr,
        "amount": flt(e.get("amount")),
        "quantity_dr": 0,
        "quantity_cr": 0,
        "currency_dr": "",
        "currency_cr": "",
        "currency_amount_dr": 0,
        "currency_amount_cr": 0,
        "content": (e.get("content") or "")[:140],
    }

    accs = {}
    for side, account in (("dr", account_dr), ("cr", account_cr)):
        slots = [("", "")] * len(SLOTS)
        if account:
            acc = _account(account, ctx)
            if acc.is_group:
                frappe.throw(_("Проводка {0}: рахунок {1} є групою").format(idx, account))
            accs[side] = acc
            slots = _map_subconto(account, acc, e.get(f"subconto_{side}"))
            if acc.quantity_accounting:
                row[f"quantity_{side}"] = flt(e.get(f"quantity_{side}"))
            if acc.currency_accounting:
                row[f"currency_{side}"] = e.get(f"currency_{side}") or ""
                row[f"currency_amount_{side}"] = flt(e.get(f"currency_amount_{side}"))
        for i, (dt, val) in enumerate(slots, start=1):
            row[f"subconto_{side}{i}_type"] = dt
            row[f"subconto_{side}{i}"] = val

    if not account_dr or not account_cr:
        # one-sided entry: allowed only for off-balance accounts
        acc = accs.get("dr") or accs.get("cr")
        if not acc.off_balance:
            frappe.throw(
                _("Проводка {0}: порожній рахунок дозволений лише для позабалансових").format(idx)
            )
    elif accs["dr"].off_balance != accs["cr"].off_balance:
        frappe.throw(_("Проводка {0}: не можна поєднувати балансовий і позабалансовий рахунок").format(idx))

    if not row["amount"] and not row["quantity_dr"] and not row["quantity_cr"]:
        frappe.throw(_("Проводка {0}: сума та кількість дорівнюють нулю").format(idx))
    return row


def _totals_key(row, side, acc):
    """Return (name, key columns) of the totals row for one side of an entry."""
    subs = []
    for i in SLOTS:
        value = row.get(f"subconto_{side}{i}") or ""
        # turnover-only subconto has no balance: store ""
        if i > len(acc.subconto) or acc.subconto[i - 1].turnover_only:
            value = ""
        subs.append(value)
    currency = (row.get(f"currency_{side}") or "") if acc.currency_accounting else ""
    account = row[f"account_{side}"]
    period = str(row["period"])
    parts = [period, row["organization"], account, *subs, currency]
    name = hashlib.sha1("|".join(parts).encode()).hexdigest()
    key = {
        "period": period,
        "organization": row["organization"],
        "account": account,
        "subconto1": subs[0],
        "subconto2": subs[1],
        "subconto3": subs[2],
        "currency": currency,
    }
    return name, key


def _add_deltas(deltas, row, ctx, sign):
    """Add the effect of one entry row (sign=1) or its removal (sign=-1)."""
    for side in SIDES:
        account = row.get(f"account_{side}")
        if not account:
            continue
        acc = _account(account, ctx)
        name, key = _totals_key(row, side, acc)
        d = deltas.get(name)
        if d is None:
            d = deltas[name] = {**key, **{k: 0 for k in TURNOVER_SUMS}}
        d["debit" if side == "dr" else "credit"] += sign * flt(row["amount"])
        d[f"quantity_{side}"] += sign * flt(row.get(f"quantity_{side}"))
        d[f"currency_{side}"] += sign * flt(row.get(f"currency_amount_{side}"))


def _apply_deltas(deltas):
    """Upsert deltas in the totals table. One atomic statement per key."""
    cols = ["period", "organization", "account", "subconto1", "subconto2", "subconto3", "currency"]
    std = std_columns()
    insert_cols = ["name", *std, *cols, *TURNOVER_SUMS]
    update = ", ".join(f"`{c}` = `{c}` + VALUES(`{c}`)" for c in TURNOVER_SUMS)
    sql = (
        f"INSERT INTO `tab{TURNOVER}` ({', '.join(f'`{c}`' for c in insert_cols)}) "
        f"VALUES ({', '.join(['%s'] * len(insert_cols))}) "
        f"ON DUPLICATE KEY UPDATE {update}, `modified` = VALUES(`modified`)"
    )
    # fixed order lowers the risk of deadlocks between two documents
    for name in sorted(deltas):
        d = deltas[name]
        frappe.db.sql(
            sql,
            [name, *std.values(), *[d[c] for c in cols], *[d[c] for c in TURNOVER_SUMS]],
        )


def _delete_empty_totals(names):
    zero = " AND ".join(f"`{c}` = 0" for c in TURNOVER_SUMS)
    for i in range(0, len(names), 500):
        chunk = names[i : i + 500]
        frappe.db.sql(
            f"DELETE FROM `tab{TURNOVER}` WHERE name IN ({', '.join(['%s'] * len(chunk))}) AND {zero}",
            chunk,
        )
