import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting.asset_documents import AssetDocument

RESERVE_ACCOUNT = "411"


class UAAssetRevaluation(AssetDocument):
    """Переоцінка ОЗ (індексація): cost and wear change by the same coefficient.

    Up:   Dt 10x Ct 411 (cost difference), Dt 411 Ct 13x (wear difference)
    Down: the same entries reversed.
    """

    doc_code = "PE"
    doc_title = "Переоцінка ОЗ"

    def validate(self):
        super().validate()
        if flt(self.new_cost) <= 0:
            frappe.throw(_("Нова вартість має бути більше нуля"))
        cost, _wear = self.cost_and_wear()
        if cost <= 0:
            frappe.throw(_("Актив {0} не має вартості на дату переоцінки").format(self.asset_title))
        if flt(self.new_cost, 2) == flt(cost, 2):
            frappe.throw(_("Нова вартість дорівнює поточній"))
        self.old_cost = cost

    def build(self):
        cost, wear = self.cost_and_wear()
        new_cost = flt(self.new_cost, 2)
        delta_cost = flt(new_cost - cost, 2)
        delta_wear = flt(wear * (new_cost / cost - 1), 2)
        entries = []
        if delta_cost > 0:
            entries.append(self.entry(self.asset_account, RESERVE_ACCOUNT, delta_cost, self.asset_sub, {}))
        elif delta_cost < 0:
            entries.append(self.entry(RESERVE_ACCOUNT, self.asset_account, -delta_cost, {}, self.asset_sub))
        if delta_wear > 0:
            entries.append(self.entry(RESERVE_ACCOUNT, self.wear_account, delta_wear, {}, self.asset_sub))
        elif delta_wear < 0:
            entries.append(self.entry(self.wear_account, RESERVE_ACCOUNT, -delta_wear, self.asset_sub, {}))
        return entries, [], []
