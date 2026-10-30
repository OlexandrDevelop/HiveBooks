import frappe
from frappe.utils import flt

from ua_accounting.accounting import regulated_report as rr


def _doc(name, ptype="write"):
    frappe.only_for(rr.READERS)
    doc = frappe.get_doc(rr.DOCTYPE, name)
    doc.check_permission(ptype)
    return doc


def _out(doc):
    return doc.as_dict(convert_dates_to_str=True)


@frappe.whitelist(methods=["POST"])
def fill_report(name):
    """Fill the lines from the ledger; lines changed by hand are kept."""
    return _out(rr.fill(_doc(name)))


@frappe.whitelist(methods=["POST"])
def set_report_line(name, code, value):
    doc = _doc(name)
    row = rr.line_of(doc, code)
    row.value, row.manual = flt(value, 2), 1
    doc.save()
    return _out(doc)


@frappe.whitelist(methods=["POST"])
def reset_report_line(name, code):
    doc = _doc(name)
    row = rr.line_of(doc, code)
    row.value, row.manual = flt(row.computed_value, 2), 0
    doc.save()
    return _out(doc)


@frappe.whitelist(methods=["POST"])
def export_report_xml(name):
    doc = _doc(name)
    res = rr.export_xml(doc)
    doc.status, doc.xsd_version = rr.EXPORTED, res["xsd_version"]
    doc.save()
    return res


@frappe.whitelist(methods=["POST"])
def reporting_calendar(organization, year):
    rr.check_access(organization)
    return rr.calendar(organization, year)
