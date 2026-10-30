"""Електронна звітність: ua_accounting.api.e_reporting.<function> (КЕП, подання до ДПС, квитанції, статистика)."""

import frappe

from ua_accounting.accounting import e_reporting as er
from ua_accounting.accounting import statistics


def _stat(name, ptype):
    er.check_roles()
    doc = frappe.get_doc(statistics.DOCTYPE, name)
    doc.check_permission(ptype)
    return doc


@frappe.whitelist(methods=["POST"])
def sign(doctype, name):
    """Sign the XML of a document with the КЕП of the organization. Returns the name of the archive record."""
    return er.sign(doctype, name)


@frappe.whitelist(methods=["POST"])
def get_signed_xml(name):
    return er.get_signed_xml(name)


@frappe.whitelist(methods=["POST"])
def verify_signature(name):
    return er.verify_signature(name)


@frappe.whitelist(methods=["POST"])
def verify_data(organization, xml, signature):
    """Check an XML and its signature (base64) for the organization: signature, chain, owner of the certificate."""
    return er.verify_data(organization, xml, signature)


@frappe.whitelist(methods=["POST"])
def ingest_receipt(name, receipt):
    """Store a receipt of ДПС (base64, CAdES) after the check of its signature and chain."""
    return er.ingest_receipt(name, receipt)


@frappe.whitelist(methods=["POST"])
def eusign_status():
    """Is the ІІТ EUSignCP library installed on the server?"""
    return er.eusign_status()


@frappe.whitelist(methods=["POST"])
def upload_key(organization, filename, key, password, certificate=None):
    """Save the key file (base64) and the password of the provider ІІТ after opening the key. Managers only."""
    return er.upload_key(organization, filename, key, password, certificate)


@frappe.whitelist(methods=["POST"])
def check_key(organization):
    """«Перевірити ключ»: owner, ЄДРПОУ, CA and validity of the certificate. Never returns the key or password."""
    return er.check_key(organization)


@frappe.whitelist(methods=["POST"])
def remove_key(organization):
    return er.remove_key(organization)


@frappe.whitelist(methods=["POST"])
def send(name):
    return er.send(name)


@frappe.whitelist(methods=["POST"])
def sync_receipts(organization):
    return er.sync_receipts(organization)


@frappe.whitelist(methods=["POST"])
def import_received_invoices(organization, date_from, date_to):
    return er.import_received_invoices(organization, date_from, date_to)


@frappe.whitelist(methods=["POST"])
def test_queue_inbound(organization, counterparty, posting_date, base, vat, number):
    """Test site only (developer mode, test provider)."""
    return er.test_queue_inbound(organization, counterparty, posting_date, base, vat, number)


@frappe.whitelist(methods=["POST"])
def statistics_fill(name):
    return statistics.fill(_stat(name, "write")).as_dict(convert_dates_to_str=True)


@frappe.whitelist(methods=["POST"])
def statistics_export_xml(name):
    doc = _stat(name, "write")
    res = statistics.export_xml(doc)
    doc.db_set("status", statistics.EXPORTED)
    return res
