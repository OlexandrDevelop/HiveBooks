import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import ledger
from ua_accounting.accounting import provisions as prov
from ua_accounting.accounting.documents import AccountingDocument


class UAVacationReserveInventory(AccountingDocument):
    """Інвентаризація резерву відпусток на кінець року.

    Required reserve = unused days x average daily pay x (1 + ЄСВ rate).
    Increase: Dt cost account Ct 471. Decrease: Dt 471 Ct 719.
    """

    doc_code = "VRI"
    doc_title = "Інвентаризація резерву відпусток"

    def validate(self):
        super().validate()
        date = getdate(self.posting_date)
        if (date.month, date.day) != (12, 31):
            frappe.throw(_("Інвентаризацію резерву відпусток проводять станом на 31 грудня"))
        settings = prov.get_settings(self.organization)
        rate = settings.esv_rate if settings else 22
        seen = set()
        total = 0.0
        for row in self.rows:
            if flt(row.unused_days) < 0 or flt(row.average_daily_pay) < 0:
                frappe.throw(_("Рядок {0}: дні і оплата не можуть бути від'ємними").format(row.idx))
            if row.person in seen:
                frappe.throw(_("Рядок {0}: працівник уже є в таблиці").format(row.idx))
            seen.add(row.person)
            row.required_amount = prov.required_vacation_reserve(row.unused_days, row.average_daily_pay, rate)
            total += row.required_amount
        self.required_amount = flt(total, 2)

    def build(self):
        self._ctx = {}
        balance = prov.credit_balance(self.organization, prov.VACATION_ACCOUNT, self.posting_date)
        delta = flt(self.required_amount - balance, 2)
        if delta > 0:
            settings = prov.get_settings(self.organization)
            if not settings:
                frappe.throw(_("Заповніть налаштування резервів організації"))
            sub = {"ExpenseItem": settings.expense_item, "Department": settings.department}
            return [self.entry(settings.vacation_expense_account or "92", prov.VACATION_ACCOUNT, delta, sub)], [], []
        if delta < 0:
            return [self.entry(prov.VACATION_ACCOUNT, prov.INCOME_ACCOUNT, -delta)], [], []
        return [], [], []

    def post_document(self):
        """The reserve may already be right: then there is nothing to post."""
        self._ctx = {}
        entries = self.build()[0]
        if entries:
            ledger.post_entries(self, entries)
