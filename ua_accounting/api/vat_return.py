import frappe

from ua_accounting.accounting import tax_xml, vat_return

RET = vat_return.RET


def _doc(name, ptype):
    frappe.has_permission(RET, ptype, throw=True)
    doc = frappe.get_doc(RET, name)
    doc.check_permission(ptype)
    return doc


@frappe.whitelist(methods=["POST"])
def fill(name):
    """Fill rows and appendices from the VAT registers. Rows edited by hand are kept."""
    doc = _doc(name, "write")
    vat_return.fill(doc)
    doc.save()
    return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def get_summary(name):
    return vat_return.summary(_doc(name, "read"))


@frappe.whitelist(methods=["POST"])
def export_xml(name):
    frappe.has_permission(RET, "export", throw=True)
    return tax_xml.export_return_with_links(_doc(name, "read"))


@frappe.whitelist(methods=["POST"])
def export_package(name):
    """Downloadable ZIP and separate official XML files for the declaration and its appendices."""
    frappe.has_permission(RET, "export", throw=True)
    return tax_xml.export_return_package(_doc(name, "read"))
