import frappe
from frappe.model.document import Document


class UAVATLiabilityEntry(Document):
    """VAT tax liability register row. Written only by accounting.vat."""

    pass


def on_doctype_update():
    table = "UA VAT Liability Entry"
    frappe.db.add_index(table, ["organization", "period"], "idx_ua_vl_org_period")
    frappe.db.add_index(table, ["counterparty", "contract"], "idx_ua_vl_cp_contract")
    frappe.db.add_index(table, ["registrar_type", "registrar"], "idx_ua_vl_registrar")
