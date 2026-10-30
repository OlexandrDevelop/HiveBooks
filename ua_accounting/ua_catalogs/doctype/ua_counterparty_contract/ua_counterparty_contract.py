import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class UACounterpartyContract(Document):
    def validate(self):
        if frappe.db.get_value("UA Counterparty", self.counterparty, "is_group"):
            frappe.throw(_("Договір не можна створити для групи контрагентів"))
        if self.valid_to and self.contract_date and getdate(self.valid_to) < getdate(self.contract_date):
            frappe.throw(_("Дата закінчення раніше за дату договору"))
        if (self.payment_days or 0) < 0:
            frappe.throw(_("Строк оплати не може бути від'ємним"))
        self.contract_title = make_title(self)


def make_title(doc):
    """Human name of a contract. The internal hash name is never shown."""
    parts = []
    if doc.contract_no:
        parts.append(f"№{doc.contract_no}")
    if doc.contract_date:
        parts.append(f"від {frappe.utils.formatdate(doc.contract_date, 'dd.mm.yyyy')}")
    if parts:
        return "Договір " + " ".join(parts)
    name = frappe.db.get_value("UA Counterparty", doc.counterparty, "counterparty_name")
    return f"Договір {name}" if name else "Договір"
