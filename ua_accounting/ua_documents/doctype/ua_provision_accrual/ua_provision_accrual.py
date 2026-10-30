import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import provisions as prov
from ua_accounting.accounting.documents import AccountingDocument

# kind -> (provision account, expense account of an increase)
ACCOUNTS = {
    prov.KIND_DOUBTFUL: (prov.RESERVE_ACCOUNT, prov.EXPENSE_ACCOUNT),
    prov.KIND_VACATION: (prov.VACATION_ACCOUNT, None),
    prov.KIND_WARRANTY: (prov.WARRANTY_ACCOUNT, prov.SALES_EXPENSE_ACCOUNT),
}


class UAProvisionAccrual(AccountingDocument):
    """Нарахування резерву.

    Doubtful debts: the difference between the required reserve and the credit balance of 38
        (increase Dt 944 Ct 38, decrease Dt 38 Ct 719).
    Vacation reserve: Dt cost account Ct 471 per cost account and subconto of the wages.
    Warranty: Dt 93 Ct 473 for the sales of the month; Dt 473 Ct 719 for the ended warranty periods.
    """

    doc_code = "PRV"
    doc_title = "Нарахування резерву"

    def validate(self):
        super().validate()
        # no rows is allowed for doubtful debts: all debts are paid and the old reserve is reversed
        if not self.rows and self.kind != prov.KIND_DOUBTFUL:
            frappe.throw(_("Немає рядків розрахунку"))
        self.account = ACCOUNTS[self.kind][0]
        self.required_amount = flt(sum(flt(r.amount) for r in self.rows), 2)
        self.current_balance = prov.credit_balance(self.organization, self.account, self.posting_date)
        if self.kind == prov.KIND_DOUBTFUL:
            self.required_amount = max(self.required_amount, 0)
            self.delta = flt(self.required_amount - self.current_balance, 2)
        elif self.kind == prov.KIND_WARRANTY:
            added, reversed_ = self.warranty_amounts()
            self.required_amount = self.delta = flt(added - reversed_, 2)
        else:
            self.delta = self.required_amount

    def warranty_amounts(self):
        """(added, reversed) of the provision. A reversal (return, end of warranty) cannot exceed the provision."""
        added = flt(sum(flt(r.amount) for r in self.rows if flt(r.amount) > 0), 2)
        reversed_ = flt(-sum(flt(r.amount) for r in self.rows if flt(r.amount) < 0), 2)
        available = max(0.0, prov.credit_balance(self.organization, prov.WARRANTY_ACCOUNT, self.posting_date)) + added
        return added, flt(min(reversed_, available), 2)

    def subconto(self, row=None):
        settings = prov.get_settings(self.organization)
        item = (row and row.expense_item) or (settings and settings.expense_item)
        department = (row and row.department) or (settings and settings.department)
        return {"ExpenseItem": item, "Department": department}

    def build(self):
        self._ctx = {}
        account, expense = ACCOUNTS[self.kind]
        entries = []
        if self.kind == prov.KIND_DOUBTFUL:
            delta = flt(self.required_amount - prov.credit_balance(self.organization, account, self.posting_date), 2)
            if delta > 0:
                entries.append(self.entry(expense, account, delta, self.subconto()))
            elif delta < 0:
                entries.append(self.entry(account, prov.INCOME_ACCOUNT, -delta))
        elif self.kind == prov.KIND_VACATION:
            for row in self.rows:
                if flt(row.amount) > 0:
                    entries.append(
                        self.entry(row.expense_account or "92", account, row.amount, self.subconto(row))
                    )
        else:
            added, reversed_ = self.warranty_amounts()
            if added:
                entries.append(self.entry(expense, account, added, self.subconto()))
            if reversed_:
                entries.append(self.entry(account, prov.INCOME_ACCOUNT, reversed_))
        return entries, [], []
