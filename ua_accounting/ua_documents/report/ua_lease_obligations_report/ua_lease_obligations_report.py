"""Зобов'язання за орендою: the debt to the lessor by every lease contract."""

import frappe
from frappe.utils import add_months, flt, getdate, nowdate

from ua_accounting.accounting import leases

LIABILITY_ACCOUNTS = {leases.OPERATING: "631", leases.FINANCE: "531"}


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "lease", "label": "Договір оренди", "fieldtype": "Link", "options": "UA Lease Agreement", "width": 130},
        {"fieldname": "lease_kind", "label": "Вид оренди", "fieldtype": "Data", "width": 140},
        {"fieldname": "contract", "label": "Договір контрагента", "fieldtype": "Link", "options": "UA Counterparty Contract", "width": 160},
        {"fieldname": "counterparty", "label": "Орендодавець", "fieldtype": "Link", "options": "UA Counterparty", "width": 180},
        {"fieldname": "liability_balance", "label": "Зобов'язання", "fieldtype": "Currency", "width": 130},
        {"fieldname": "remaining_payments", "label": "Залишок платежів", "fieldtype": "Currency", "width": 130},
        {"fieldname": "current_part", "label": "Поточна частина", "fieldtype": "Currency", "width": 130},
        {"fieldname": "long_term_part", "label": "Довгострокова частина", "fieldtype": "Currency", "width": 140},
        {"fieldname": "next_payment_date", "label": "Наступний платіж", "fieldtype": "Date", "width": 110},
        {"fieldname": "next_payment_amount", "label": "Сума наступного платежу", "fieldtype": "Currency", "width": 140},
    ]
    if not filters.organization:
        return columns, []
    frappe.has_permission("UA Lease Agreement", "read", throw=True)
    date_to = getdate(filters.date_to or nowdate())
    rows = []
    for lease in frappe.get_all(
        leases.LEASE,
        filters={"organization": filters.organization},
        fields=["name", "lease_kind", "contract", "counterparty"],
        order_by="creation asc",
        limit_page_length=0,
    ):
        row = operating_row(lease, date_to) if lease.lease_kind == leases.OPERATING else finance_row(lease, date_to)
        if row:
            rows.append(row)
    return columns, rows


def base_row(lease):
    return {
        "lease": lease.name,
        "lease_kind": lease.lease_kind,
        "contract": lease.contract,
        "counterparty": lease.counterparty,
        "remaining_payments": 0,
        "current_part": 0,
        "long_term_part": 0,
        "next_payment_date": None,
        "next_payment_amount": 0,
    }


def liability(organization, account, registrars=None, contract=None, date_to=None):
    """Credit minus debit of the account for documents (or the contract subconto) up to the date."""
    cond, args = "", []
    if registrars is not None:
        if not registrars:
            return 0.0
        cond = "and (registrar_type, registrar) in (" + ", ".join(["(%s, %s)"] * len(registrars)) + ")"
        for doctype, name in registrars:
            args += [doctype, name]
    else:
        cond = "and ((account_cr = %s and subconto_cr2 = %s) or (account_dr = %s and subconto_dr2 = %s))"
        args += [account, contract, account, contract]
    res = frappe.db.sql(
        f"""select coalesce(sum(case when account_cr = %s then amount else 0 end), 0)
        - coalesce(sum(case when account_dr = %s then amount else 0 end), 0)
        from `tabUA Accounting Entry` where organization = %s and posting_date <= %s {cond}""",
        [account, account, organization, date_to, *args],
    )
    return flt(res[0][0], 2)


def operating_row(lease, date_to):
    org = frappe.db.get_value(leases.LEASE, lease.name, "organization")
    periods = [p for p in leases.periods(lease.name) if p[0] <= date_to]
    if not periods:
        return None
    row = base_row(lease)
    # rent is paid by the contract: the debt is the balance of 631 for the contract
    row["liability_balance"] = row["current_part"] = liability(org, "631", contract=lease.contract, date_to=date_to)
    row["remaining_payments"] = row["liability_balance"]
    return row


def finance_row(lease, date_to):
    receipt = leases.finance_receipt(lease.name, date_to)
    if not receipt:
        return None
    doc = frappe.get_doc(leases.LEASE, lease.name)
    registrars = [(leases.FIN_RECEIPT, receipt.name)]
    for doctype in (leases.INTEREST, leases.PAYMENT):
        registrars += [
            (doctype, d)
            for d in frappe.get_all(doctype, filters={"lease": lease.name, "docstatus": 1, "posting_date": ("<=", date_to)}, pluck="name")
        ]
    row = base_row(lease)
    row["liability_balance"] = liability(doc.organization, "531", registrars=registrars, date_to=date_to)
    paid = set(
        getdate(d)
        for d in frappe.get_all(
            leases.PAYMENT, filters={"lease": lease.name, "docstatus": 1, "posting_date": ("<=", date_to)}, pluck="schedule_date"
        )
    )
    accrued = set(
        getdate(d)
        for d in frappe.get_all(
            leases.INTEREST, filters={"lease": lease.name, "docstatus": 1, "posting_date": ("<=", date_to)}, pluck="schedule_date"
        )
    )
    limit = add_months(date_to, 12)
    current = 0.0
    for r in sorted(doc.schedule, key=lambda r: getdate(r.payment_date)):
        d = getdate(r.payment_date)
        if d in paid:
            continue
        row["remaining_payments"] += flt(r.amount)
        if not row["next_payment_date"]:
            row["next_payment_date"], row["next_payment_amount"] = d, flt(r.amount, 2)
        if d <= limit:
            current += flt(r.principal) + (flt(r.interest) if d in accrued else 0)
    row["remaining_payments"] = flt(row["remaining_payments"], 2)
    row["current_part"] = flt(min(current, max(row["liability_balance"], 0)), 2)
    row["long_term_part"] = flt(max(row["liability_balance"] - row["current_part"], 0), 2)
    return row
