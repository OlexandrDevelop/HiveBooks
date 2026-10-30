"""Helpers of the lease documents (operating lease and finance lease of the lessee).

Operating lease (НП(С)БО 14): the object is on the off-balance account 01, the rent is an expense of the period.
Finance lease: asset and liability at the lower of the fair value and the present value of the minimum payments,
interest by the effective interest method.
"""

import calendar
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, getdate
from dateutil.relativedelta import relativedelta

LEASE = "UA Lease Agreement"
RECEIPT = "UA Leased Asset Receipt"
RETURN = "UA Leased Asset Return"
RENT = "UA Rent Accrual"
FIN_RECEIPT = "UA Finance Lease Receipt"
INTEREST = "UA Lease Interest Accrual"
PAYMENT = "UA Lease Payment"

OPERATING = "Операційна оренда"
FINANCE = "Фінансова оренда"

OFF_BALANCE_ACCOUNT = "01"

# documents that use an agreement: the key terms cannot change after them
USED_BY = (RECEIPT, RETURN, FIN_RECEIPT, INTEREST, PAYMENT)


# ---------------------------------------------------------------- finance lease schedule


def year_fraction(start, end):
    """Years between two dates: whole months when the day matches, else days / 365."""
    start, end = getdate(start), getdate(end)
    delta = relativedelta(end, start)
    if not delta.days:
        return delta.years + delta.months / 12
    return (end - start).days / 365


def present_value(rate, start, rows):
    """Discounted sum of the payments `rows` (payment_date, amount) at the annual `rate` in percent."""
    return sum(flt(r.amount) / (1 + rate / 100) ** year_fraction(start, r.payment_date) for r in rows)


def effective_rate(target, start, rows, low):
    """Annual rate in percent (not below `low`) at which the present value of `rows` equals `target`."""
    if present_value(low, start, rows) <= target:
        return low
    high = max(low * 2, 100.0)
    while present_value(high, start, rows) > target and high < 1e6:
        high *= 2
    for _i in range(100):
        mid = (low + high) / 2
        if present_value(mid, start, rows) > target:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def calculate_schedule(doc):
    """Fill present value, recognised value, interest, principal and balance of a finance lease."""
    rows = sorted(doc.schedule, key=lambda r: getdate(r.payment_date))
    doc.schedule = rows
    for idx, r in enumerate(rows, start=1):
        r.idx = idx
    pv = flt(present_value(flt(doc.discount_rate), doc.start_date, rows), 2)
    doc.present_value = pv
    fair = flt(doc.fair_value)
    doc.recognised_value = flt(min(fair, pv) if fair > 0 else pv, 2)
    rate = flt(doc.discount_rate)
    if doc.recognised_value < pv:
        # the fair value is lower: the implicit rate of the lease is higher than the discount rate
        rate = effective_rate(doc.recognised_value, doc.start_date, rows, rate)
    doc.effective_rate = rate
    balance, previous = doc.recognised_value, getdate(doc.start_date)
    for idx, r in enumerate(rows):
        if idx == len(rows) - 1:
            interest = flt(flt(r.amount) - balance, 2)
        else:
            interest = flt(balance * ((1 + rate / 100) ** year_fraction(previous, r.payment_date) - 1), 2)
        r.interest = max(interest, 0)
        r.principal = flt(flt(r.amount) - r.interest, 2)
        balance = flt(balance + r.interest - flt(r.amount), 2)
        r.balance = max(balance, 0)
        previous = getdate(r.payment_date)


def schedule_row(lease, schedule_date):
    """Row of the agreement schedule for the payment date."""
    for r in lease.schedule:
        if getdate(r.payment_date) == getdate(schedule_date):
            return r
    frappe.throw(_("Дати {0} немає в графіку платежів договору {1}").format(schedule_date, lease.name))


# ---------------------------------------------------------------- possession of an operating lease


def submitted(doctype, lease):
    return frappe.get_all(
        doctype,
        filters={"lease": lease, "docstatus": 1},
        fields=["name", "posting_date", "amount"],
        order_by="posting_date asc, creation asc",
        limit_page_length=0,
    )


def periods(lease):
    """[(from, to or None, amount)] of the object being at the lessee: receipts paired with returns by order."""
    receipts, returns = submitted(RECEIPT, lease), submitted(RETURN, lease)
    out = []
    for idx, r in enumerate(receipts):
        end = getdate(returns[idx].posting_date) if idx < len(returns) else None
        out.append((getdate(r.posting_date), end, flt(r.amount)))
    return out


def open_period(lease, date=None):
    """The period of the lease that is open (no return yet) and started not after `date`."""
    for start, end, amount in periods(lease):
        if end is None and (date is None or start <= getdate(date)):
            return start, amount
    return None


def rent_days(lease, month_end, end_date):
    """Days of the month in which the object was at the lessee (up to the end of the agreement)."""
    first, last = get_first_day(month_end), getdate(month_end)
    if end_date:
        last = min(last, getdate(end_date))
    covered = set()
    for start, end, _amount in periods(lease):
        begin, finish = max(start, first), min(end or last, last)
        d = begin
        while d <= finish:
            covered.add(d)
            d += timedelta(days=1)
    days = len(covered)
    return days, calendar.monthrange(first.year, first.month)[1]


def used_by_documents(lease):
    """Submitted documents of the agreement (the key terms are then locked)."""
    for doctype in USED_BY:
        if frappe.db.exists(doctype, {"lease": lease, "docstatus": 1}):
            return True
    return bool(rent_accruals(lease))


def rent_accruals(lease, from_date=None):
    """Submitted rent accrual documents of the lease (from a posting date)."""
    sql = (
        "select distinct p.name, p.posting_date from `tabUA Rent Accrual` p "
        "join `tabUA Rent Accrual Line` l on l.parent = p.name "
        "where p.docstatus = 1 and l.lease = %s"
    )
    args = [lease]
    if from_date:
        sql += " and p.posting_date >= %s"
        args.append(getdate(from_date))
    return frappe.db.sql(sql, args, as_dict=True)


# ---------------------------------------------------------------- finance lease state


def finance_receipt(lease, date=None):
    """The submitted receipt of a finance lease (posted not after `date`)."""
    filters = {"lease": lease, "docstatus": 1}
    if date:
        filters["posting_date"] = ("<=", getdate(date))
    return frappe.db.get_value(FIN_RECEIPT, filters, ["name", "posting_date", "amount"], as_dict=True)


def period_doc(doctype, lease, schedule_date, exclude=None, statuses=(0, 1)):
    """A document of the lease for the schedule date (draft or submitted)."""
    filters = {"lease": lease, "schedule_date": getdate(schedule_date), "docstatus": ("in", list(statuses))}
    if exclude:
        filters["name"] = ("!=", exclude)
    return frappe.db.get_value(doctype, filters, "name")


def check_previous_periods(lease, schedule_date):
    """Interest and payment of every earlier period must be done first."""
    for r in lease.schedule:
        if getdate(r.payment_date) >= getdate(schedule_date):
            continue
        if flt(r.interest) and not period_doc(INTEREST, lease.name, r.payment_date, statuses=(1,)):
            frappe.throw(_("Спочатку нарахуйте відсотки за період {0}").format(r.payment_date))
        if not period_doc(PAYMENT, lease.name, r.payment_date, statuses=(1,)):
            frappe.throw(_("Спочатку проведіть лізинговий платіж за {0}").format(r.payment_date))


def year_ahead(date):
    return add_months(getdate(date), 12)


# ---------------------------------------------------------------- base of the documents


from ua_accounting.accounting.documents import AccountingDocument  # noqa: E402


class LeaseDocument(AccountingDocument):
    """Document of an agreement: loads the agreement and checks its kind and organization."""

    kind = OPERATING

    def load_lease(self):
        lease = frappe.get_doc(LEASE, self.lease)
        if lease.organization != self.organization:
            frappe.throw(_("Договір оренди {0} належить іншій організації").format(self.lease))
        if lease.lease_kind != self.kind:
            frappe.throw(_("Договір {0}: потрібен вид оренди «{1}»").format(self.lease, self.kind))
        return lease

    def settle_sub(self, lease):
        return {"Counterparty": lease.counterparty, "Contract": lease.contract}
