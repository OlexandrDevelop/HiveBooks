import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import leases

ASSET_ACCOUNT = "152"
LIABILITY_ACCOUNT = "531"


class UAFinanceLeaseReceipt(leases.LeaseDocument):
    """Отримання майна у фінансову оренду: Dt 152 Kt 531 at the lower of the fair value and the present value."""

    doc_code = "FLR"
    doc_title = "Отримання майна у фінансову оренду"
    kind = leases.FINANCE

    def validate(self):
        super().validate()
        lease = self.load_lease()
        self.amount = flt(lease.recognised_value, 2)
        other = frappe.db.get_value(
            leases.FIN_RECEIPT, {"lease": self.lease, "docstatus": ("<", 2), "name": ("!=", self.name or "")}
        )
        if other:
            frappe.throw(_("Майно за договором {0} вже отримано: {1}").format(self.lease, other))

    def before_cancel(self):
        if frappe.db.exists(leases.INTEREST, {"lease": self.lease, "docstatus": 1}) or frappe.db.exists(
            leases.PAYMENT, {"lease": self.lease, "docstatus": 1}
        ):
            frappe.throw(_("За договором {0} є відсотки або платежі: спочатку скасуйте їх").format(self.lease))
        super().before_cancel()

    def build(self):
        lease = frappe.get_doc(leases.LEASE, self.lease)
        return [
            self.entry(ASSET_ACCOUNT, LIABILITY_ACCOUNT, self.amount, {"FixedAsset": lease.asset}, self.settle_sub(lease))
        ], [], []
