import frappe

from ua_accounting.accounting import tax


@frappe.whitelist(methods=["POST"])
def create_on_basis(tax_invoice):
    """Draft РК with the lines copied from a submitted ПН."""
    frappe.has_permission(tax.RK, "create", throw=True)
    pn = frappe.get_doc(tax.PN, tax_invoice)
    pn.check_permission("read")
    values = tax.adjustment_from_invoice(pn)
    doc = frappe.new_doc(tax.RK)
    lines = values.pop("lines")
    doc.update(values)
    for line in lines:
        doc.append("lines", line)
    doc.insert()
    return doc.name


@frappe.whitelist()
def make_adjustment(source_name):
    """Unsaved РК for the button «Створити на підставі»."""
    frappe.has_permission(tax.RK, "create", throw=True)
    pn = frappe.get_doc(tax.PN, source_name)
    pn.check_permission("read")
    values = tax.adjustment_from_invoice(pn)
    doc = frappe.new_doc(tax.RK)
    lines = values.pop("lines")
    doc.update(values)
    for line in lines:
        doc.append("lines", line)
    return doc
