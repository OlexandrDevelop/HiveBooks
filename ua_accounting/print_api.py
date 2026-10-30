"""Batch print: one wrong name fails the whole batch (a silent gap in a stack of forms is worse than an error)."""

import json

import frappe
from frappe import _
from frappe.utils.print_format import download_multi_pdf as frappe_download_multi_pdf


def _names(name):
    if isinstance(name, str) and name.strip().startswith("["):
        return json.loads(name)
    return name if isinstance(name, list) else [name]


@frappe.whitelist()
def download_multi_pdf(doctype, name, format=None, no_letterhead=False, letterhead=None, options=None):
    if isinstance(doctype, str):
        for docname in _names(name):
            if not frappe.db.exists(doctype, docname):
                frappe.throw(_("{0} {1} не знайдено").format(_(doctype), docname), frappe.DoesNotExistError)
    return frappe_download_multi_pdf(doctype, name, format, no_letterhead, letterhead, options)
