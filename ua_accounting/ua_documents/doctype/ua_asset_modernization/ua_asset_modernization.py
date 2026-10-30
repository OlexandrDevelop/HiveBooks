import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import assets
from ua_accounting.accounting.asset_documents import AssetDocument


class UAAssetModernization(AssetDocument):
    """Модернізація ОЗ: Dt 10x Ct 152 by the amount. The cost grows; a new term may be given."""

    doc_code = "MO"
    doc_title = "Модернізація ОЗ"

    def validate(self):
        super().validate()
        if flt(self.amount) <= 0:
            frappe.throw(_("Сума модернізації має бути більше нуля"))
        if (self.new_useful_life_months or 0) < 0:
            frappe.throw(_("Новий строк корисного використання не може бути від'ємним"))

    def build(self):
        entry = self.entry(
            self.asset_account, assets.PURCHASE_ACCOUNT[self.asset_type], self.amount, self.asset_sub, self.asset_sub
        )
        return [entry], [], []
