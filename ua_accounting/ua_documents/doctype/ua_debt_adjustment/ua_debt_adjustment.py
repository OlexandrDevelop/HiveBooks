import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting.documents import AccountingDocument, base_currency, settlement_balance
from ua_accounting.accounting.utils import title_of

OFFSET = "Взаємозалік"
ASSIGNMENT = "Переуступка"
WRITE_OFF = "Списання боргу"
RECEIVABLE = "Дебіторська"
PAYABLE = "Кредиторська"

RECEIVABLE_ACCOUNT = "361"
PAYABLE_ACCOUNT = "631"
WRITE_OFF_EXPENSE_ACCOUNT = "944"
WRITE_OFF_INCOME_ACCOUNT = "717"
OFF_BALANCE_ACCOUNT = "071"


class UADebtAdjustment(AccountingDocument):
    """Коригування боргу.

    Offset and assignment:    Dt 631 (supplier, contract 2) Ct 361 (buyer, contract)
    Write-off of receivable:  Dt 944 Ct 361, off-balance Dt 071
    Write-off of payable:     Dt 631 Ct 717
    """

    doc_code = "DAD"
    doc_title = "Коригування боргу"

    def validate(self):
        super().validate()
        if flt(self.amount) <= 0:
            frappe.throw(_("Сума має бути більше нуля"))
        if self.kind == WRITE_OFF:
            if not self.debt_side:
                frappe.throw(_("Вкажіть, яку заборгованість списуємо: дебіторську чи кредиторську"))
            if self.debt_side == RECEIVABLE and not self.expense_item:
                frappe.throw(_("Вкажіть статтю витрат для списання дебіторської заборгованості"))
        else:
            self.debt_side = None
            self.expense_item = None
        self.check_parties()

    def parties(self):
        """[(side, counterparty, contract)] that the document touches."""
        first = (self.counterparty, self.contract)
        second = (self.counterparty2, self.contract2)
        if self.kind == WRITE_OFF:
            if self.debt_side == RECEIVABLE:
                return [(RECEIVABLE, *(first if first[0] else second))]
            return [(PAYABLE, *(second if second[0] else first))]
        return [(RECEIVABLE, *first), (PAYABLE, *second)]

    def check_parties(self):
        currencies = set()
        for _side, counterparty, contract in self.parties():
            if not counterparty or not contract:
                frappe.throw(_("Вкажіть контрагента і договір"))
            row = frappe.db.get_value(
                "UA Counterparty Contract", contract, ["counterparty", "organization", "currency"], as_dict=True
            )
            if not row or row.counterparty != counterparty:
                frappe.throw(
                    _("Договір {0} не належить контрагенту {1}").format(
                        title_of("UA Counterparty Contract", contract), title_of("UA Counterparty", counterparty)
                    )
                )
            if row.organization != self.organization:
                frappe.throw(_("Договір {0} укладено з іншою організацією").format(title_of("UA Counterparty Contract", contract)))
            currencies.add(row.currency or base_currency())
        if len(currencies) > 1:
            frappe.throw(_("Валюти договорів різні: зарахування можливе лише в одній валюті"))
        if currencies and currencies != {base_currency()}:
            frappe.throw(_("Коригування боргу за договорами у валюті не підтримується"))

    def check_debt(self, side, counterparty, contract):
        account = RECEIVABLE_ACCOUNT if side == RECEIVABLE else PAYABLE_ACCOUNT
        debt = settlement_balance(
            self.organization, account, counterparty, contract, "dr" if side == RECEIVABLE else "cr",
            self.posting_date, self._ctx,
        )
        if flt(self.amount, 2) > debt:
            frappe.throw(
                _("Сума {0} більша за борг {1} за договором {2}").format(
                    frappe.format(self.amount, {"fieldtype": "Currency"}),
                    frappe.format(max(debt, 0), {"fieldtype": "Currency"}),
                    title_of("UA Counterparty Contract", contract),
                )
            )

    def build(self):
        self._ctx = {}
        amount = flt(self.amount, 2)
        for side, counterparty, contract in self.parties():
            self.check_debt(side, counterparty, contract)
        (_s1, cp1, ct1) = self.parties()[0]
        if self.kind in (OFFSET, ASSIGNMENT):
            (_s2, cp2, ct2) = self.parties()[1]
            entries = [
                self.entry(
                    PAYABLE_ACCOUNT, RECEIVABLE_ACCOUNT, amount,
                    {"Counterparty": cp2, "Contract": ct2}, {"Counterparty": cp1, "Contract": ct1},
                )
            ]
        elif self.debt_side == RECEIVABLE:
            entries = [
                self.entry(
                    WRITE_OFF_EXPENSE_ACCOUNT, RECEIVABLE_ACCOUNT, amount,
                    {"ExpenseItem": self.expense_item}, {"Counterparty": cp1, "Contract": ct1},
                ),
                self.entry(OFF_BALANCE_ACCOUNT, "", amount),
            ]
        else:
            entries = [
                self.entry(
                    PAYABLE_ACCOUNT, WRITE_OFF_INCOME_ACCOUNT, amount, {"Counterparty": cp1, "Contract": ct1}, None
                )
            ]
        return entries, [], []
