import frappe
from frappe import _
from frappe.model.document import Document


class UAExchangeLog(Document):
    """The journal of the exchange: written by the exchange methods only, nobody edits or deletes a row."""

    def validate(self):
        if not self.flags.exchange_log:
            frappe.throw(_("Журнал обміну заповнюється автоматично"), frappe.PermissionError)

    def on_trash(self):
        if not frappe.flags.in_install:
            frappe.throw(_("Записи журналу обміну не видаляються"), frappe.PermissionError)
