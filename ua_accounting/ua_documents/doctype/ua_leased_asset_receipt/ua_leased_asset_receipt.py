import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import leases


class UALeasedAssetReceipt(leases.LeaseDocument):
    """Отримання майна в оренду: off-balance Dt 01 (subconto: the asset)."""

    doc_code = "LRC"
    doc_title = "Отримання майна в оренду"
    kind = leases.OPERATING

    def validate(self):
        super().validate()
        lease = self.load_lease()
        self.amount = flt(lease.asset_value, 2)
        if self.amount <= 0:
            frappe.throw(_("У договорі {0} не вказано вартість об'єкта").format(lease.name))
        if leases.open_period(self.lease):
            frappe.throw(_("Майно за договором {0} вже отримано і ще не повернено").format(self.lease))

    def before_cancel(self):
        if leases.rent_accruals(self.lease):
            frappe.throw(_("За договором {0} нараховано оренду: спочатку скасуйте нарахування").format(self.lease))
        if leases.submitted(leases.RETURN, self.lease):
            frappe.throw(_("За договором {0} є повернення майна: спочатку скасуйте його").format(self.lease))
        super().before_cancel()

    def build(self):
        asset = frappe.db.get_value(leases.LEASE, self.lease, "asset")
        return [self.entry(leases.OFF_BALANCE_ACCOUNT, "", self.amount, {"FixedAsset": asset})], [], []
