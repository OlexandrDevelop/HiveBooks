import frappe
from frappe.model.document import Document


class UAAccountTurnover(Document):
    """Monthly turnovers by organization, account, subconto 1-3 and currency.

    Rows are written only by ua_accounting.accounting.ledger.
    """

    pass


def on_doctype_update():
    table = "UA Account Turnover"
    frappe.db.add_index(table, ["organization", "account", "period"], "idx_ua_at_org_acc_period")
    frappe.db.add_index(table, ["account", "period"], "idx_ua_at_acc_period")
    for i in (1, 2, 3):
        frappe.db.add_index(table, [f"subconto{i}"], f"idx_ua_at_subconto{i}")
