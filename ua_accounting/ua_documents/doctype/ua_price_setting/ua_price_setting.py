import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.accounting.utils import title_of


class UAPriceSetting(AccountingDocument):
    """Встановлення цін номенклатури. Does not post: prices are read from submitted documents."""

    doc_code = "PST"
    doc_title = "Встановлення цін номенклатури"
    posts = False

    def check_organization(self):
        pass  # prices do not belong to an organization

    def validate(self):
        super().validate()
        if not self.prices:
            frappe.throw(_("Заповніть табличну частину «Ціни»"))
        for row in self.prices:
            if flt(row.price) < 0:
                frappe.throw(_("Рядок {0}: ціна не може бути від’ємною").format(row.idx))
            if frappe.db.get_value("UA Item", row.item, "is_group"):
                frappe.throw(_("Рядок {0}: {1} є групою номенклатури").format(row.idx, title_of("UA Item", row.item)))
