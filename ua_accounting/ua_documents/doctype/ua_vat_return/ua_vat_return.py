import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_first_day, get_last_day, getdate

from ua_accounting.accounting.documents import make_doc_name
from ua_accounting.accounting.vat_return import FORM_VERSION
from ua_accounting.accounting import regulatory


class UAVATReturn(Document):
    """Декларація з ПДВ. Not submittable: filled from the VAT registers, then edited by hand."""

    doc_code = "VR"

    def autoname(self):
        self.name = make_doc_name(self, self.period_to)

    def validate(self):
        if not self.organization or not frappe.db.get_value("UA Organization", self.organization, "vat_payer"):
            frappe.throw(_("Декларацію з ПДВ подає лише платник ПДВ"))
        start, end = getdate(self.period_from), getdate(self.period_to)
        if start != get_first_day(start) or end != get_last_day(start):
            frappe.throw(_("Період декларації має бути календарним місяцем"))
        if frappe.db.exists(
            "UA VAT Return",
            {"organization": self.organization, "period_from": start, "name": ("!=", self.name)},
        ):
            frappe.throw(_("Декларація за цей період вже існує"))
        self.form_version = regulatory.form_version_info(
            "VAT_RETURN", start, 26, FORM_VERSION + " v.26"
        )["schema_version"].split()[0]
        self.status = self.status or "Чернетка"
