import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import leases

LIABILITY_ACCOUNT = "531"
BANK_ACCOUNT = "311"


class UALeasePayment(leases.LeaseDocument):
    """Лізинговий платіж: Dt 531 Kt 311, the amount is taken from the schedule."""

    doc_code = "LPM"
    doc_title = "Лізинговий платіж"
    kind = leases.FINANCE

    def validate(self):
        super().validate()
        lease = self.load_lease()
        receipt = leases.finance_receipt(self.lease)
        if not receipt or getdate(receipt.posting_date) > getdate(self.posting_date):
            frappe.throw(_("Майно за договором {0} ще не отримано у фінансову оренду").format(self.lease))
        row = leases.schedule_row(lease, self.schedule_date)
        self.schedule_date = row.payment_date
        self.amount = flt(row.amount, 2)
        if leases.period_doc(leases.PAYMENT, self.lease, self.schedule_date, exclude=self.name or ""):
            frappe.throw(_("Платіж за {0} вже є").format(self.schedule_date))
        if flt(row.interest) and not leases.period_doc(leases.INTEREST, self.lease, self.schedule_date, statuses=(1,)):
            frappe.throw(_("Спочатку нарахуйте відсотки за {0}").format(self.schedule_date))
        leases.check_previous_periods(lease, self.schedule_date)
        if frappe.db.get_value("UA Bank Account", self.bank_account, "organization") != self.organization:
            frappe.throw(_("Банківський рахунок належить іншій організації"))

    def before_cancel(self):
        for doctype in (leases.INTEREST, leases.PAYMENT):
            later = frappe.db.exists(
                doctype,
                {"lease": self.lease, "docstatus": 1, "schedule_date": (">", getdate(self.schedule_date))},
            )
            if later:
                frappe.throw(_("Є проведені документи за пізніші періоди: спочатку скасуйте їх"))
        super().before_cancel()

    def build(self):
        lease = frappe.get_doc(leases.LEASE, self.lease)
        return [
            self.entry(
                LIABILITY_ACCOUNT, BANK_ACCOUNT, self.amount, self.settle_sub(lease), {"BankAccount": self.bank_account}
            )
        ], [], []
