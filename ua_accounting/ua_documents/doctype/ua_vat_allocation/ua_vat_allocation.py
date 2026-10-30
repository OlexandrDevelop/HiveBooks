import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import ledger
from ua_accounting.accounting.documents import TAX_VAT, AccountingDocument

EXPENSE_ACCOUNT = "949"  # spec_gap: 1C account of the credit that is not allowed
CREDIT_ACCOUNT = "644"


class UAVATAllocation(AccountingDocument):
    """Розподіл ПДВ (ст. 198/199 ПКУ): Dt 949 Ct 644 for the part of the credit that is not allowed."""

    doc_code = "VA"
    doc_title = "Розподіл ПДВ"

    def validate(self):
        super().validate()
        if getdate(self.period_to) < getdate(self.period_from):
            frappe.throw(_("Період задано неправильно"))
        if flt(self.taxable_turnover) < 0 or flt(self.exempt_turnover) < 0:
            frappe.throw(_("Обсяги операцій не можуть бути від'ємними"))
        turnover = flt(self.taxable_turnover) + flt(self.exempt_turnover)
        if turnover:
            self.taxable_share = flt(flt(self.taxable_turnover) * 100 / turnover, 2)
        if flt(self.disallowed_credit) < 0 or flt(self.allowed_credit) < 0:
            frappe.throw(_("Суми не можуть бути від'ємними"))
        if flt(self.allowed_credit + self.disallowed_credit, 2) != flt(self.credit_total, 2):
            frappe.throw(_("Дозволена і недозволена частини разом мають дорівнювати податковому кредиту"))

    def on_submit(self):
        self._ctx = {}
        if flt(self.disallowed_credit) > 0:
            ledger.post_entries(
                self,
                [
                    self.entry(
                        EXPENSE_ACCOUNT, CREDIT_ACCOUNT, self.disallowed_credit, {}, {"TaxType": TAX_VAT}
                    )
                ],
            )
