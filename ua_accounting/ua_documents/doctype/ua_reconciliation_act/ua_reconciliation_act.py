import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.accounting.utils import title_of

# settlement accounts with the counterparty: 36 buyers, 37 other debtors, 63 suppliers, 68 other creditors
SETTLEMENT_ACCOUNTS = "^(36|37|63|68)"


class UAReconciliationAct(AccountingDocument):
    """Акт звірки взаєморозрахунків. Does not post: it reads the ledger on save.

    Balance is Dt − Kt of all settlement accounts of the counterparty (and the contract, if given):
    a positive balance means the counterparty owes us.
    """

    doc_code = "RAC"
    doc_title = "Акт звірки взаєморозрахунків"
    posts = False

    def autoname(self):
        self.posting_date = self.date_to  # only for the number: the document has no such field
        super().autoname()
        del self.__dict__["posting_date"]

    def validate(self):
        super().validate()
        if getdate(self.date_from) > getdate(self.date_to):
            frappe.throw(_("Початок періоду пізніше за його кінець"))
        if self.contract:
            row = frappe.db.get_value(
                "UA Counterparty Contract", self.contract, ["counterparty", "organization"], as_dict=True
            )
            if not row or row.counterparty != self.counterparty or row.organization != self.organization:
                frappe.throw(
                    _("Договір {0} не належить контрагенту {1}").format(
                        title_of("UA Counterparty Contract", self.contract), title_of("UA Counterparty", self.counterparty)
                    )
                )
        self.fill()

    def match(self, side):
        """SQL condition: the counterparty (and the contract) in a subconto of a settlement account."""
        slots = (1, 2, 3)
        one = " or ".join(f"(subconto_{side}{i}_type = 'UA Counterparty' and subconto_{side}{i} = %(cp)s)" for i in slots)
        cond = f"account_{side} regexp %(accounts)s and ({one})"
        if self.contract:
            two = " or ".join(f"(subconto_{side}{i}_type = 'UA Counterparty Contract' and subconto_{side}{i} = %(ct)s)" for i in slots)
            cond += f" and ({two})"
        return cond

    def movements(self, where, params, group):
        """{key: (debit, credit)} of the entries by the `group` columns."""
        result = {}
        for side, pos in (("dr", 0), ("cr", 1)):
            rows = frappe.db.sql(
                f"""select {group and group + ',' or ''} sum(amount) as total from `tabUA Accounting Entry`
                where organization = %(org)s and {where} and {self.match(side)}
                {f'group by {group}' if group else ''}""",
                params,
                as_dict=True,
            )
            for r in rows:
                key = tuple(r[c.strip()] for c in group.split(",")) if group else ()
                pair = list(result.get(key, (0.0, 0.0)))
                pair[pos] = flt(pair[pos] + flt(r.total), 2)
                result[key] = tuple(pair)
        return result

    def fill(self):
        params = {
            "org": self.organization, "cp": self.counterparty, "ct": self.contract or "",
            "accounts": SETTLEMENT_ACCOUNTS, "start": self.date_from, "end": self.date_to,
        }
        before = self.movements("posting_date < %(start)s", params, "").get((), (0.0, 0.0))
        period = self.movements(
            "posting_date >= %(start)s and posting_date <= %(end)s", params, "posting_date, registrar_type, registrar"
        )
        self.rows = []
        debit_total = credit_total = 0.0
        for (day, doctype, name), (debit, credit) in sorted(period.items(), key=lambda kv: (str(kv[0][0]), kv[0][2])):
            if not debit and not credit:
                continue
            self.append("rows", {"posting_date": day, "document_type": doctype, "document": name,
                                 "debit": debit, "credit": credit})
            debit_total += debit
            credit_total += credit
        self.opening_balance = flt(before[0] - before[1], 2)
        self.turnover_debit = flt(debit_total, 2)
        self.turnover_credit = flt(credit_total, 2)
        self.closing_balance = flt(self.opening_balance + self.turnover_debit - self.turnover_credit, 2)
        self.discrepancy = flt(self.closing_balance - flt(self.their_balance), 2)
