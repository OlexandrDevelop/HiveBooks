"""Posting API of the accounting register.

Documents call:
    post_entries(doc, entries)    from on_submit
    cancel_entries(doc)           from on_cancel
    repost_entries(doc, entries)  cancel + post in one transaction

The module never commits. It runs in the transaction of the caller.
Movements go through the core RecordSet of the register "UA Accounting Entry" and the
monthly totals (UA Account Turnover) through the core accounting totals adapter
(frappe.beeone.accounting_totals), with the column mapping `totals_mapping()` below.
post_entries appends rows to the registrar (as before); cancel_entries removes all of
them; repost_entries is cancel + post.
"""

import frappe
from frappe import _
from frappe.beeone import accounting_totals
from frappe.beeone.accounting_meta import normalize_accounting_entry
from frappe.beeone.registers import record_set
from frappe.utils import flt, getdate

from ua_accounting.accounting import simplified_tax, tax_ledger, vat
from ua_accounting.accounting.utils import first_of_month, next_names, part_of, pick

ENTRY = "UA Accounting Entry"
TURNOVER = "UA Account Turnover"
SIDES = ("dr", "cr")
SLOTS = (1, 2, 3)
CHART = "UA Account"



def totals_mapping():
    """Columns of the entry and totals DocTypes for the core accounting totals adapter (hook beeone_accounting_totals)."""
    both = {"debit": "dr", "credit": "cr"}
    return {
        "chart": CHART,
        "period": "period",
        "organization": "organization",
        "amount": "amount",
        "account": {side: f"account_{short}" for side, short in both.items()},
        "subconto": {side: [f"subconto_{short}{i}" for i in SLOTS] for side, short in both.items()},
        "quantity": {side: f"quantity_{short}" for side, short in both.items()},
        "currency": {side: f"currency_{short}" for side, short in both.items()},
        "currency_amount": {side: f"currency_amount_{short}" for side, short in both.items()},
        "totals": {
            "period": "period",
            "organization": "organization",
            "account": "account",
            "subconto": ["subconto1", "subconto2", "subconto3"],
            "currency": "currency",
            "debit": "debit",
            "credit": "credit",
            "quantity": {"debit": "quantity_dr", "credit": "quantity_cr"},
            "currency_amount": {"debit": "currency_dr", "credit": "currency_cr"},
        },
    }


# ---------------------------------------------------------------- public API


def post_entries(doc, entries):
    """Write entries of the registrar `doc` and add them to the monthly totals."""
    entries = list(entries or [])
    if not entries:
        return
    ctx = {}
    rows = [_build_row(doc, e, idx, ctx) for idx, e in enumerate(entries, start=1)]
    # moves the name sequence over rows made with AUTO_INCREMENT, once per process
    next_names(ENTRY, 0)
    record_set(ENTRY, doc.doctype, doc.name, keep_blank=True, part=part_of(doc)).append(rows)
    tax_ledger.post_rows(doc, rows, entries)
    _refresh_invoices(doc)


def cancel_entries(doc):
    """Delete entries of the registrar and take them out of the totals."""
    keys = _invoice_contracts(doc)
    record_set(ENTRY, doc.doctype, doc.name, part=part_of(doc)).delete()
    tax_ledger.cancel_rows(doc)
    vat.cancel_vat_entries(doc)
    _refresh_invoices(doc, keys)


def _invoice_contracts(doc):
    from ua_accounting.accounting import invoice

    return invoice.registrar_contracts(doc.doctype, doc.name)


def _refresh_invoices(doc, keys=None):
    """The Invoice states count the payments that no Invoice owns: recompute the contracts a registrar touched."""
    from ua_accounting.accounting import invoice

    invoice.refresh_registrar(doc.doctype, doc.name, keys)


def repost_entries(doc, entries):
    cancel_entries(doc)
    post_entries(doc, entries)


@frappe.whitelist(methods=["POST"])
def rebuild_totals(organization=None, from_period=None):
    """Recompute the totals table from entries. For repair and checks.

    Without filters all totals are rebuilt. `organization` and `from_period` (the month of the
    date and later) limit the rebuild; other totals stay. Manager only.
    """
    frappe.only_for(("UA Accounting Manager", "System Manager"))
    from_period = first_of_month(from_period) if from_period else None
    return accounting_totals.rebuild(ENTRY, organization, from_period)


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


def _build_row(doc, e, idx, ctx):
    posting_date = pick(doc, e, "posting_date")
    organization = pick(doc, e, "organization")
    if not posting_date or not organization:
        frappe.throw(_("Проводка {0}: потрібні дата та організація").format(idx))
    posting_date = getdate(posting_date)
    if not frappe.db.exists("UA Organization", organization):
        frappe.throw(_("Організацію {0} не знайдено").format(organization))

    entry = normalize_accounting_entry(
        frappe.get_cached_doc("Chart of Accounts", CHART),
        debit=e.get("account_dr"),
        credit=e.get("account_cr"),
        amount=flt(e.get("amount")),
        quantity_debit=flt(e.get("quantity_dr")),
        quantity_credit=flt(e.get("quantity_cr")),
        currency_debit=e.get("currency_dr"),
        currency_credit=e.get("currency_cr"),
        currency_amount_debit=flt(e.get("currency_amount_dr")),
        currency_amount_credit=flt(e.get("currency_amount_cr")),
        subconto_debit=e.get("subconto_dr"),
        subconto_credit=e.get("subconto_cr"),
    )
    row = {
        "posting_date": posting_date,
        "period": first_of_month(posting_date),
        "registrar_type": doc.doctype,
        "registrar": doc.name,
        "line_no": idx,
        "organization": organization,
        "account_dr": (entry["debit"] or {}).get("account", ""),
        "account_cr": (entry["credit"] or {}).get("account", ""),
        "amount": entry["amount"],
        "content": (e.get("content") or "")[:140],
    }
    for side, short in (("debit", "dr"), ("credit", "cr")):
        data = entry.get(side) or {}
        if data:
            simplified_tax.check_posting_account(organization, posting_date, data["account"], ctx)
        row[f"quantity_{short}"] = flt(data.get("quantity"))
        row[f"currency_{short}"] = data.get("currency") or ""
        row[f"currency_amount_{short}"] = flt(data.get("currency_amount"))
        slots = data.get("subconto") or []
        for i in SLOTS:
            slot = slots[i - 1] if i <= len(slots) else {}
            row[f"subconto_{short}{i}_type"] = slot.get("doctype") or ""
            row[f"subconto_{short}{i}"] = slot.get("value") or ""
    return row


def get_lock_date(doc):
    """Get the lock date from UA Organization for the document's organization.

    Called by the beeone core through the hook beeone_lock_date.
    Returns the lock date, or None if there's no lock.
    """
    organization = doc.get("organization")
    if not organization:
        return None
    return frappe.db.get_value("UA Organization", organization, "edit_lock_date")


def check_period(doc):
    """Check if the document's date is locked via the beeone period lock mechanism.

    Wrapper that calls the core's check_period_lock to invoke the hook system.
    Raises an error if the document is in a locked period and the user is not exempted.
    """
    from frappe.beeone.registers.posting import check_period_lock
    check_period_lock(doc)
