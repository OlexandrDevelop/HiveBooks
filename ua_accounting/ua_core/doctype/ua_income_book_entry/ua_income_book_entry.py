import frappe
from frappe import _
from frappe.model.document import Document


class UAIncomeBookEntry(Document):
    """Рядок Книги обліку доходів. Written only by accounting.simplified_tax (bulk insert)."""

    def before_insert(self):
        frappe.throw(_("Книгу обліку доходів заповнюють проведенням документів"))


def on_doctype_update():
    table = "UA Income Book Entry"
    frappe.db.add_index(table, ["organization", "posting_date"], "idx_ua_ib_org_date")
    frappe.db.add_index(table, ["registrar_type", "registrar"], "idx_ua_ib_registrar")
