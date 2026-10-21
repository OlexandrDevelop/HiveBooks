import frappe
from frappe import _
from frappe.model.document import Document


class UACounterpartyContract(Document):
    def validate(self):
        if frappe.db.get_value("UA Counterparty", self.counterparty, "is_group"):
            frappe.throw(_("Договір не можна створити для групи контрагентів"))
        if self.valid_to and self.contract_date and self.valid_to < self.contract_date:
            frappe.throw(_("Дата закінчення раніше за дату договору"))
        if not self.contract_title:
            self.contract_title = " ".join(
                p for p in (self.contract_no and f"№{self.contract_no}", self.contract_date and f"від {self.contract_date}") if p
            ) or self.name
