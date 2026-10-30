"""Податкові накладні: creation on basis, register, ЄРПН status, XML."""

import frappe
from frappe import _

from ua_accounting.accounting import tax, tax_xml


def _new_doc(doctype, values):
    frappe.has_permission(doctype, "create", throw=True)
    doc = frappe.new_doc(doctype)
    lines = values.pop("lines")
    doc.update(values)
    for line in lines:
        doc.append("lines", line)
    doc.insert()
    return doc.name


@frappe.whitelist(methods=["POST"])
def create_on_basis(basis_doctype, basis_name, direction=None):
    """Draft ПН for a sale, a receipt or an advance payment. The direction follows the basis document."""
    if basis_doctype not in tax.BASIS_DIRECTION:
        frappe.throw(_("Для документа {0} податкова накладна не створюється").format(basis_doctype))
    frappe.has_permission(tax.PN, "create", throw=True)
    basis = frappe.get_doc(basis_doctype, basis_name)
    basis.check_permission("read")
    return _new_doc(tax.PN, tax.invoice_from_basis(basis))


@frappe.whitelist(methods=["POST"])
def create_consolidated(organization, date_from, date_to, invoice_kind):
    frappe.has_permission(tax.PN, "create", throw=True)
    return _new_doc(tax.PN, tax.consolidated_invoice(organization, date_from, date_to, invoice_kind))


@frappe.whitelist(methods=["POST"])
def register_data(organization, date_from, date_to, direction=None, erpn_status=None, counterparty=None):
    return tax.register_data(organization, date_from, date_to, direction, erpn_status, counterparty)


@frappe.whitelist(methods=["POST"])
def set_erpn_status(name, status, reg_number=None, reg_date=None, doctype=None):
    return tax.set_status(name, status, reg_number, reg_date, doctype)


@frappe.whitelist(methods=["POST"])
def export_xml(doctype, name):
    if doctype not in (tax.PN, tax.RK):
        frappe.throw(_("Вивантаження XML доступне лише для податкової накладної і розрахунку коригування"))
    frappe.has_permission(doctype, "export", throw=True)
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    if doc.docstatus != 1:
        frappe.throw(_("Вивантажують лише проведені документи"))
    return tax_xml.export(doc)


def _draft(basis_doctype, source_name):
    """Unsaved ПН for the button «Створити на підставі»."""
    frappe.has_permission(tax.PN, "create", throw=True)
    basis = frappe.get_doc(basis_doctype, source_name)
    basis.check_permission("read")
    values = tax.invoice_from_basis(basis)
    doc = frappe.new_doc(tax.PN)
    lines = values.pop("lines")
    doc.update(values)
    for line in lines:
        doc.append("lines", line)
    return doc


@frappe.whitelist()
def make_from_sale(source_name):
    return _draft(tax.SALE, source_name)


@frappe.whitelist()
def make_from_receipt(source_name):
    return _draft(tax.PURCHASE, source_name)


@frappe.whitelist()
def make_from_cash_receipt(source_name):
    return _draft(tax.CASH_IN, source_name)


@frappe.whitelist()
def make_from_cash_payment(source_name):
    return _draft(tax.CASH_OUT, source_name)
