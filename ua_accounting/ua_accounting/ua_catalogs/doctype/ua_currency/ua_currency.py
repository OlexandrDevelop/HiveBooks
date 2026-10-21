import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class UACurrency(Document):
    def validate(self):
        if self.is_base:
            other = frappe.db.get_value(
                "UA Currency", {"is_base": 1, "name": ("!=", self.name)}, "name"
            )
            if other:
                frappe.throw(_("Базова валюта вже задана: {0}").format(other))


@frappe.whitelist()
def get_rate(currency, date=None):
    """Return the rate for one unit of currency in base currency on the date.

    Uses the last rate on or before the date. Base currency gives 1.
    """
    if not currency or frappe.db.get_value("UA Currency", currency, "is_base"):
        return 1.0
    rows = frappe.db.sql(
        """select rate, multiplicity from `tabUA Currency Rate`
        where parent = %s and parenttype = 'UA Currency' and date <= %s
        order by date desc limit 1""",
        (currency, getdate(date)),
        as_dict=True,
    )
    if not rows:
        return 0.0
    return flt(rows[0].rate) / (rows[0].multiplicity or 1)
