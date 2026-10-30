"""VAT calculations that do not post anything: allocation of the credit (ст. 198/199) and the registration limit."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import tax, vat

SMALL_SHARE = 5.0  # ПКУ ст. 198.5: up to 5 % of non-taxable operations the whole credit stays


def credit_total(organization, period_from, period_to):
    """VAT credit register sum of the period (the caller cannot override it)."""
    total = frappe.db.sql(
        f"select coalesce(sum(vat_amount), 0) from `tab{vat.CREDIT}` "
        "where organization = %s and posting_date between %s and %s",
        (organization, getdate(period_from), getdate(period_to)),
    )[0][0]
    return flt(total, 2)


def allocate(organization, period_from, period_to, taxable_ops=None, exempt_ops=None):
    taxable, exempt = flt(taxable_ops), flt(exempt_ops)
    if taxable < 0 or exempt < 0:
        frappe.throw(_("Обсяги операцій не можуть бути від'ємними"))
    credit = credit_total(organization, period_from, period_to)
    total = taxable + exempt
    result = {"taxable_share": 100.0, "credit_total": credit, "allowed": credit, "disallowed": 0.0, "applied": False}
    if not total:
        return result
    result["taxable_share"] = flt(taxable * 100 / total, 2)
    if exempt * 100 / total > SMALL_SHARE:
        disallowed = flt(credit * exempt / total, 2)
        result.update(disallowed=disallowed, allowed=flt(credit - disallowed, 2), applied=True)
    return result


def registration_limit(organization, as_of):
    as_of = getdate(as_of)
    setting = frappe.get_all(
        "UA VAT Setting",
        filters={"organization": organization, "date": ("<=", as_of)},
        fields=["date", "registration_limit_start", "paid_in"],
        order_by="date desc, creation desc",
        limit=1,
    )
    start = flt(setting[0].registration_limit_start, 2) if setting else 0.0
    paid_in = flt(setting[0].paid_in, 2) if setting else 0.0
    since = setting[0].date if setting else getdate("1900-01-01")
    sums = {}
    for direction in (tax.RECEIVED, tax.ISSUED):
        total = 0.0
        for doctype, field in ((tax.PN, "total_vat"), (tax.RK, "total_delta_vat")):
            total += flt(
                frappe.db.sql(
                    f"select coalesce(sum(`{field}`), 0) from `tab{doctype}` "
                    "where organization = %s and direction = %s and docstatus = 1 and erpn_status = %s "
                    "and erpn_reg_date between %s and %s",
                    (organization, direction, tax.STATUS_REGISTERED, since, as_of),
                )[0][0]
            )
        sums[direction] = flt(total, 2)
    credit_registered, liability_issued = sums[tax.RECEIVED], sums[tax.ISSUED]
    return {
        "start": start,
        "paid_in": paid_in,
        "credit_registered": credit_registered,
        "liability_issued": liability_issued,
        "available": flt(start + paid_in + credit_registered - liability_issued, 2),
    }
