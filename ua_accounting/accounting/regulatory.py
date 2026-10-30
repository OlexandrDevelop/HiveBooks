"""Regulatory update process: dated parameters, versions of report forms, release notes (T-458).

Rates and limits are rows of UA Regulatory Parameter (read by `parameter`); the form for a report is chosen by the
START of the reporting period, not by the filing date.
"""

import re

import frappe
from frappe import _
from frappe.beeone.registers import slice_last
from frappe.utils import getdate, today

from ua_accounting.ua_core.reads import system_reads

READERS = ("UA Accountant", "UA Accounting Manager", "UA Chief Accountant", "System Manager")
PARAM = "UA Regulatory Parameter"
FORM = "UA Report Form Version"
NOTE = "UA Release Note"
XSD_ID = re.compile(r"^[A-Z]\d{5,7}$")


def parameter_row(code, date=None):
    day = getdate(date or today())
    with system_reads():
        rows = slice_last(PARAM, at=day, filters={"parameter_code": code}, group_by=[])
    if not rows:
        frappe.throw(_("Нормативний параметр {0} не задано на {1}").format(code, day))
    return frappe._dict(rows[0], parameter_code=code)


@frappe.whitelist()
def get_parameter(code, date=None):
    """Value of a dated legal parameter: the row with the latest `effective_from` <= date (default today)."""
    frappe.only_for(READERS)
    row = parameter_row(code, date)
    return {"code": row.parameter_code, "value": row.value, "effective_from": str(row.effective_from),
            "legal_basis": row.legal_basis}


def form_version_row(form_code, period_start):
    rows = frappe.get_all(
        FORM, filters={"form_code": form_code, "status": "Діє", "effective_from": ("<=", getdate(period_start))},
        fields=["form_code", "form_name", "version_no", "effective_from", "schema_version", "xsd_file",
                "legal_basis", "status"],
        order_by="effective_from desc", limit=1,
    )
    if not rows:
        frappe.throw(_("Немає версії форми {0} для періоду з {1}").format(form_code, getdate(period_start)))
    return rows[0]


@frappe.whitelist()
def get_form_version(form_code, period_start):
    """Version of the form valid for a reporting period that starts on `period_start`."""
    frappe.only_for(READERS)
    row = form_version_row(form_code, period_start)
    row["effective_from"] = str(row.effective_from)
    return row


def form_version_info(form_code, period_start, default_version, default_schema):
    """Version, schema id and XSD file name for an XML header.

    A form with no rows at all keeps the built-in defaults. A form with rows must have a version for the period:
    a period before its first version is rejected, as in get_form_version.
    """
    if not frappe.db.exists(FORM, {"form_code": form_code}):
        return {"version": default_version, "schema_version": default_schema,
                "xsd": default_schema.split()[0] + ".xsd"}
    row = form_version_row(form_code, period_start)
    no = row.version_no
    schema = row.schema_version or default_schema
    token = schema.split()[0]
    return {"version": int(no) if str(no).isdigit() else no, "schema_version": schema,
            "xsd": token + ".xsd" if XSD_ID.match(token) else default_schema.split()[0] + ".xsd"}


@frappe.whitelist()
def get_release_notes(since=None):
    """Release notes, newest first; only those with release_date >= since."""
    frappe.only_for(READERS)
    filters = {"release_date": (">=", getdate(since))} if since else {}
    return frappe.get_all(
        NOTE, filters=filters, order_by="release_date desc, creation desc",
        fields=["name", "release_version", "release_date", "title", "change_type", "effective_from",
                "description", "patch_name"],
    )
