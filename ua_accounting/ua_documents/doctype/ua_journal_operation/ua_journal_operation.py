import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.accounting.ledger import SLOTS


class UAJournalOperation(AccountingDocument):
    """Операція (бухгалтерська): entries typed by hand. Also used for opening balances."""

    doc_code = "OP"
    doc_title = "Операція"

    def validate(self):
        super().validate()
        if not self.entries:
            frappe.throw(_("Додайте проводки"))
        for row in self.entries:
            if not row.account_dr and not row.account_cr:
                frappe.throw(_("Рядок {0}: вкажіть рахунок").format(row.idx))
            for side in ("dr", "cr"):
                self.set_subconto_types(row, side)
            if flt(row.tax_amount) < 0:
                frappe.throw(_("Рядок {0}: сума ПО не може бути від'ємною").format(row.idx))
        self.follow_amount_in_tax()

    def before_insert(self):
        """Empty ПО means «equals БО»: the field is a number, so the default is written once, at insert."""
        for row in self.entries:
            if row.get("tax_amount") is None:
                row.tax_amount = flt(row.amount)

    def follow_amount_in_tax(self):
        """A draft row whose ПО followed БО keeps following it when the amount is edited."""
        before = self.get_doc_before_save()
        if not before:
            return
        old = {r.name: r for r in before.entries}
        for row in self.entries:
            p = old.get(row.name)
            if p and flt(p.tax_amount) == flt(p.amount) and flt(row.tax_amount) == flt(p.tax_amount):
                row.tax_amount = flt(row.amount)

    def set_subconto_types(self, row, side):
        """The type of a subconto value comes from the account, not from the user."""
        account = row.get(f"account_{side}")
        types = []
        if account:
            types = frappe.db.sql(
                """select t.reference_doctype, t.is_dynamic from `tabUA Account Subconto` s
                left join `tabUA Subconto Type` t on t.name = s.subconto_type
                where s.parent = %s and s.parenttype = 'UA Account' order by s.idx""",
                account,
                as_dict=True,
            )
        for i in SLOTS:
            meta = types[i - 1] if i <= len(types) else None
            if not meta:
                row.set(f"subconto_{side}{i}", None)
                row.set(f"subconto_{side}{i}_type", None)
            elif not meta.is_dynamic:
                row.set(f"subconto_{side}{i}_type", meta.reference_doctype)

    def build(self):
        entries = []
        for row in self.entries:
            e = {
                "account_dr": row.account_dr or "",
                "account_cr": row.account_cr or "",
                "amount": flt(row.amount),
                "tax_amount": flt(row.tax_amount) if row.get("tax_amount") is not None else None,
                "quantity_dr": flt(row.quantity_dr),
                "quantity_cr": flt(row.quantity_cr),
                "currency_dr": row.currency_dr,
                "currency_cr": row.currency_cr,
                "currency_amount_dr": flt(row.currency_amount_dr),
                "currency_amount_cr": flt(row.currency_amount_cr),
                "content": row.content or self.content,
            }
            for side in ("dr", "cr"):
                e[f"subconto_{side}"] = self.subconto_dict(row, side)
            entries.append(e)
        return entries, [], []

    def subconto_dict(self, row, side):
        account = row.get(f"account_{side}")
        if not account:
            return {}
        from ua_accounting.accounting import ledger

        acc = ledger._account(account, self._ctx)
        result = {}
        for i, meta in enumerate(acc.subconto, start=1):
            value = row.get(f"subconto_{side}{i}")
            if not value:
                continue
            if meta.is_dynamic:
                result[meta.subconto_type] = (row.get(f"subconto_{side}{i}_type"), value)
            else:
                result[meta.subconto_type] = value
        return result
