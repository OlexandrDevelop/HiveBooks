import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import payroll as calc
from ua_accounting.accounting.documents import AccountingDocument

BANK = "Банк"
LIABILITY = "661"


class UASalaryPayment(AccountingDocument):
    """Виплата зарплати (відомість): Dt 661 (person) Ct 311 (bank) or 301 (cash desk)."""

    doc_code = "SP"
    doc_title = "Виплата зарплати"

    def validate(self):
        super().validate()
        self.check_cash_side()
        payroll = frappe.db.get_value(
            "UA Payroll", self.payroll, ["organization", "docstatus"], as_dict=True
        )
        if not payroll or payroll.docstatus != 1:
            frappe.throw(_("Нарахування зарплати {0} не проведене").format(self.payroll))
        if payroll.organization != self.organization:
            frappe.throw(_("Нарахування зарплати належить іншій організації"))
        due = calc.payroll_due(self.payroll, self.name)
        if not self.rows:
            for employee, amount in due.items():
                if amount > 0:
                    self.append("rows", {"employee": employee, "amount": float(amount)})
        paid = {}
        for row in self.rows:
            if row.employee not in due:
                frappe.throw(_("Рядок {0}: співробітника немає в нарахуванні").format(row.idx))
            if flt(row.amount) <= 0:
                frappe.throw(_("Рядок {0}: сума має бути більше нуля").format(row.idx))
            paid[row.employee] = paid.get(row.employee, calc.D(0)) + calc.D(row.amount)
        for employee, amount in paid.items():
            if amount > due[employee]:
                frappe.throw(_("Виплата {0} перевищує суму до виплати {1}").format(amount, due[employee]))
        if not self.rows:
            frappe.throw(_("Немає сум до виплати"))
        self.total_amount = flt(sum(flt(r.amount) for r in self.rows), 2)

    def check_cash_side(self):
        if self.payment_type == BANK:
            if not self.bank_account:
                frappe.throw(_("Вкажіть банківський рахунок"))
            self.cash_desk = None
            owner = frappe.db.get_value("UA Bank Account", self.bank_account, "organization")
        else:
            if not self.cash_desk:
                frappe.throw(_("Вкажіть касу"))
            self.bank_account = None
            owner = frappe.db.get_value("UA Cash Desk", self.cash_desk, "organization")
        if owner != self.organization:
            frappe.throw(_("Рахунок або каса належить іншій організації"))

    def build(self):
        if self.payment_type == BANK:
            account, cash_sub = "311", {"BankAccount": self.bank_account}
        else:
            account, cash_sub = "301", {"CashDesk": self.cash_desk}
        entries = []
        for row in self.rows:
            person = frappe.db.get_value("UA Employee", row.employee, "person")
            entries.append(self.entry(LIABILITY, account, row.amount, {"Person": person}, cash_sub))
        return entries, [], []
