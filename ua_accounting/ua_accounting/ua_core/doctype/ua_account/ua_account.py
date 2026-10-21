import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet

MAX_SUBCONTO = 3


class UAAccount(NestedSet):
    nsm_parent_field = "parent_ua_account"

    def validate(self):
        self.display_name = f"{self.account_code} {self.account_name}"
        self.validate_subconto()
        self.validate_off_balance()
        self.validate_posted_changes()

    def validate_subconto(self):
        if len(self.subconto) > MAX_SUBCONTO:
            frappe.throw(_("Рахунок може мати не більше {0} видів субконто").format(MAX_SUBCONTO))
        seen = set()
        for row in self.subconto:
            if row.subconto_type in seen:
                frappe.throw(
                    _("Рядок {0}: вид субконто {1} вказано двічі").format(row.idx, row.subconto_type)
                )
            seen.add(row.subconto_type)

    def validate_off_balance(self):
        if self.parent_ua_account and frappe.db.get_value(
            "UA Account", self.parent_ua_account, "off_balance"
        ):
            self.off_balance = 1

    def validate_posted_changes(self):
        """Block changes that would break totals keys when entries exist."""
        if self.is_new():
            return
        before = self.get_doc_before_save()
        if not before or not has_entries(self.name):
            return

        def sub_sig(doc):
            return [(r.subconto_type, int(r.turnover_only or 0)) for r in doc.subconto]

        if (
            sub_sig(before) != sub_sig(self)
            or bool(before.is_group) != bool(self.is_group)
            or bool(before.currency_accounting) != bool(self.currency_accounting)
            or bool(before.quantity_accounting) != bool(self.quantity_accounting)
        ):
            frappe.throw(
                _(
                    "За рахунком {0} є проводки. Не можна змінювати субконто, "
                    "ознаку групи, валютний та кількісний облік."
                ).format(self.name)
            )


def has_entries(account):
    return bool(
        frappe.db.exists("UA Accounting Entry", {"account_dr": account})
        or frappe.db.exists("UA Accounting Entry", {"account_cr": account})
    )
