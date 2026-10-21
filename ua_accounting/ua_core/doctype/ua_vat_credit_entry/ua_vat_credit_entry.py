import frappe
from frappe.model.document import Document


class UAVATCreditEntry(Document):
    """VAT tax credit register row. Written only by accounting.vat."""

    pass


def on_doctype_update():
    table = "UA VAT Credit Entry"
    frappe.db.add_index(table, ["organization", "period"], "idx_ua_vc_org_period")
    frappe.db.add_index(table, ["counterparty", "contract"], "idx_ua_vc_cp_contract")
    frappe.db.add_index(table, ["registrar_type", "registrar"], "idx_ua_vc_registrar")
