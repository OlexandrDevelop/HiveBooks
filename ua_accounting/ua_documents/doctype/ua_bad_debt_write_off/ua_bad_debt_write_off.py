import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import provisions as prov
from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.accounting.utils import title_of

OFF_BALANCE_ACCOUNT = "071"


class UABadDebtWriteoff(AccountingDocument):
    """Списання безнадійної заборгованості.

    Dt 38 Ct 361 up to the credit balance of the reserve, the rest Dt 944 Ct 361, off-balance Dt 071.
    """

    doc_code = "BDW"
    doc_title = "Списання безнадійної заборгованості"

    def validate(self):
        super().validate()
        if flt(self.amount) <= 0:
            frappe.throw(_("Сума має бути більше нуля"))
        contract = frappe.db.get_value(
            "UA Counterparty Contract", self.contract, ["counterparty", "organization"], as_dict=True
        )
        if not contract or contract.counterparty != self.counterparty:
            frappe.throw(
                _("Договір {0} не належить контрагенту {1}").format(
                    title_of("UA Counterparty Contract", self.contract), title_of("UA Counterparty", self.counterparty)
                )
            )
        if contract.organization != self.organization:
            frappe.throw(_("Договір {0} укладено з іншою організацією").format(title_of("UA Counterparty Contract", self.contract)))

    def buckets(self):
        """Debts of the settlement document (or the documentless debt), largest first."""
        rows = prov.receivables(
            self.organization, self.posting_date, self.counterparty, self.contract, self.settlement_doc or ""
        )
        return sorted(rows, key=lambda r: -r["debt"])

    def debt(self):
        return flt(sum(r["debt"] for r in self.buckets()), 2)

    def build(self):
        self._ctx = {}
        amount = flt(self.amount, 2)
        debts = self.buckets()
        debt = flt(sum(r["debt"] for r in debts), 2)
        if amount > debt:
            frappe.throw(
                _("Сума {0} більша за борг {1} за документом розрахунків {2}").format(
                    frappe.format(amount, {"fieldtype": "Currency"}),
                    frappe.format(debt, {"fieldtype": "Currency"}),
                    self.settlement_doc or _("без документа"),
                )
            )
        entries = []
        left = amount
        # the reserve 38 is shared by all buckets of one write-off: it is used once
        self.reserve_left = max(0.0, prov.credit_balance(self.organization, prov.RESERVE_ACCOUNT, self.posting_date))
        for bucket in debts:
            part = flt(min(left, bucket["debt"]), 2)
            if part <= 0:
                continue
            left = flt(left - part, 2)
            entries.extend(self.write_off_part(bucket, part))
        entries.append(self.entry(OFF_BALANCE_ACCOUNT, "", amount))
        return entries, [], []

    def write_off_part(self, bucket, amount):
        """Dt 38 / Dt 944 Ct receivable account of the bucket (361, 362...)."""
        account = bucket["account"]
        sub = {"Counterparty": self.counterparty, "Contract": self.contract}
        if bucket["settlement_doc"]:
            sub["SettlementDoc"] = (bucket["doc_type"], bucket["settlement_doc"])
        from_reserve = flt(min(amount, self.reserve_left), 2)
        to_expense = flt(amount - from_reserve, 2)
        self.reserve_left = flt(self.reserve_left - from_reserve, 2)
        # currency accounts keep the currency amount in proportion to the written-off part
        cur_total = flt(bucket["currency_amount"] * amount / bucket["debt"], 2) if bucket["currency"] else 0
        extra = {"currency_cr": bucket["currency"]} if bucket["currency"] else {}
        entries = []
        if from_reserve:
            cur = flt(cur_total * from_reserve / amount, 2)
            entries.append(
                self.entry(prov.RESERVE_ACCOUNT, account, from_reserve, None, sub, currency_amount_cr=cur, **extra)
            )
        if to_expense:
            settings = prov.get_settings(self.organization)
            if not settings or not settings.expense_item or not settings.department:
                frappe.throw(_("Заповніть статтю витрат і підрозділ у налаштуваннях резервів організації"))
            cur = flt(cur_total - (flt(cur_total * from_reserve / amount, 2) if from_reserve else 0), 2)
            entries.append(
                self.entry(
                    prov.EXPENSE_ACCOUNT, account, to_expense,
                    {"ExpenseItem": settings.expense_item, "Department": settings.department}, sub,
                    currency_amount_cr=cur, **extra,
                )
            )
        return entries
