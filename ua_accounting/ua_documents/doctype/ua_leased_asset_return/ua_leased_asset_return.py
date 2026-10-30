import frappe
from frappe import _

from ua_accounting.accounting import leases


class UALeasedAssetReturn(leases.LeaseDocument):
    """Повернення майна з оренди: off-balance Kt 01."""

    doc_code = "LRT"
    doc_title = "Повернення майна з оренди"
    kind = leases.OPERATING

    def validate(self):
        super().validate()
        self.load_lease()
        period = leases.open_period(self.lease, self.posting_date)
        if not period:
            frappe.throw(_("Майно за договором {0} не отримано або вже повернено").format(self.lease))
        self.amount = period[1]
        if leases.rent_accruals(self.lease, leases.get_first_day(self.posting_date)):
            frappe.throw(_("Оренду за місяць повернення або пізніше вже нараховано: спочатку скасуйте нарахування"))

    def before_cancel(self):
        receipts, returns = leases.submitted(leases.RECEIPT, self.lease), leases.submitted(leases.RETURN, self.lease)
        position = next((i for i, r in enumerate(returns) if r.name == self.name), None)
        if position is not None and len(receipts) > position + 1:
            frappe.throw(_("Після цього повернення є нове отримання майна: спочатку скасуйте його"))
        month = leases.get_first_day(self.posting_date)
        if leases.rent_accruals(self.lease, month):
            frappe.throw(_("Оренду за місяць повернення вже нараховано: спочатку скасуйте нарахування"))
        super().before_cancel()

    def build(self):
        asset = frappe.db.get_value(leases.LEASE, self.lease, "asset")
        return [self.entry("", leases.OFF_BALANCE_ACCOUNT, self.amount, None, {"FixedAsset": asset})], [], []
