import frappe
from frappe import _
from frappe.utils import add_days

from ua_accounting.accounting import assets
from ua_accounting.accounting.asset_documents import AssetDocument


class UAAssetTransfer(AssetDocument):
    """Переміщення ОЗ: no entries. The department and the responsible person of the asset card change."""

    doc_code = "PO"
    doc_title = "Переміщення ОЗ"
    posts = False

    def validate(self):
        super().validate()
        if not self.new_department and not self.new_responsible:
            frappe.throw(_("Вкажіть новий підрозділ або нову матеріально відповідальну особу"))

    def on_submit(self):
        meta = frappe.get_meta(self.asset_type)
        old = {}
        for new, field, old_field in (
            ("new_department", "department", "old_department"),
            ("new_responsible", "responsible", "old_responsible"),
        ):
            if self.get(new) and meta.has_field(field):
                old[old_field] = assets.card_value_at(
                    self.asset_type, self.asset, field, add_days(self.posting_date, -1), self.organization
                )
        if old:
            frappe.db.set_value(self.doctype, self.name, old, update_modified=False)
        self.refresh_card()

    def on_cancel(self):
        self.refresh_card()

    def refresh_card(self):
        """The card shows the latest state; the history is in the submitted transfers."""
        meta = frappe.get_meta(self.asset_type)
        values = {
            field: assets.card_value_at(self.asset_type, self.asset, field, None, self.organization)
            for field in ("department", "responsible")
            if meta.has_field(field) and self.get(f"new_{field}")
        }
        if values:
            frappe.db.set_value(self.asset_type, self.asset, values, update_modified=False)
