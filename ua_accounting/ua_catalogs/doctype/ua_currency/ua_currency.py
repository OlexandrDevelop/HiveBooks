import frappe
from frappe import _
from frappe.beeone.registers import slice_last
from frappe.model.document import Document
from frappe.utils import flt, getdate

from ua_accounting.ua_core.reads import system_reads


RATE = "UA Exchange Rate"


class UACurrency(Document):
    def on_update(self):
        sync_rates(self)

    def on_trash(self):
        frappe.db.delete(RATE, {"currency": self.name})

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
    frappe.has_permission("UA Currency", "read", throw=True)
    if not currency or frappe.db.get_value("UA Currency", currency, "is_base"):
        return 1.0
    row = rate_row(currency, date)
    if not row:
        return 0.0
    return flt(row.rate) / (row.multiplicity or 1)


def rate_row(currency, date=None):
    """The latest row of the rate register on or before the date: `rate`, `multiplicity`, `date`. None if there is none."""
    with system_reads():
        rows = slice_last(RATE, at=getdate(date), filters={"currency": currency}, group_by=[])
    return frappe._dict(rows[0]) if rows else None


def sync_rates(currency):
    """Write the rows of `rates` to the rate register: one row per date, the last row of a date wins."""
    wanted = {}
    for row in currency.rates or []:
        if row.date:
            wanted[getdate(row.date)] = (flt(row.rate), row.multiplicity or 1)
    seen = set()
    for row in frappe.get_all(RATE, filters={"currency": currency.name}, fields=["name", "date", "rate", "multiplicity"], order_by="creation asc"):
        day = getdate(row.date)
        if day not in wanted or day in seen:
            frappe.delete_doc(RATE, row.name, ignore_permissions=True, force=True)
            continue
        seen.add(day)
        if (flt(row.rate), row.multiplicity or 1) != wanted[day]:
            frappe.db.set_value(RATE, row.name, {"rate": wanted[day][0], "multiplicity": wanted[day][1]})
    for day, (rate, multiplicity) in wanted.items():
        if day not in seen:
            frappe.get_doc(
                {"doctype": RATE, "currency": currency.name, "date": day, "rate": rate, "multiplicity": multiplicity}
            ).insert(ignore_permissions=True)
