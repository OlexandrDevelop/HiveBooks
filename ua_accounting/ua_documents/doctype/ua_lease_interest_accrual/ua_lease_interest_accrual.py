import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import leases

EXPENSE_ACCOUNT = "951"
LIABILITY_ACCOUNT = "531"


class UALeaseInterestAccrual(leases.LeaseDocument):
    """Нарахування відсотків за фінансовою орендою: Dt 951 Kt 531 (interest of the schedule row)."""

    doc_code = "LIN"
    doc_title = "Нарахування відсотків за фінансовою орендою"
    kind = leases.FINANCE

    def validate(self):
        super().validate()
        lease = self.load_lease()
        receipt = leases.finance_receipt(self.lease)
        if not receipt or getdate(receipt.posting_date) > getdate(self.posting_date):
            frappe.throw(_("Майно за договором {0} ще не отримано у фінансову оренду").format(self.lease))
        row = leases.schedule_row(lease, self.schedule_date)
        self.schedule_date = row.payment_date
        self.amount = flt(row.interest, 2)
        if self.amount <= 0:
            frappe.throw(_("За цей період відсотків немає"))
        if leases.period_doc(leases.INTEREST, self.lease, self.schedule_date, exclude=self.name or ""):
            frappe.throw(_("Відсотки за {0} вже нараховано").format(self.schedule_date))
        leases.check_previous_periods(lease, self.schedule_date)

    def before_cancel(self):
        for r in frappe.get_all(
            leases.PAYMENT,
            filters={"lease": self.lease, "docstatus": 1, "schedule_date": (">=", self.schedule_date)},
            limit=1,
        ):
            frappe.throw(_("Період вже сплачено ({0}): спочатку скасуйте платіж").format(r.name))
        super().before_cancel()

    def build(self):
        lease = frappe.get_doc(leases.LEASE, self.lease)
        return [self.entry(EXPENSE_ACCOUNT, LIABILITY_ACCOUNT, self.amount, {}, self.settle_sub(lease))], [], []
