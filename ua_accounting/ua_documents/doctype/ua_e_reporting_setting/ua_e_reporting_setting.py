import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from ua_accounting.accounting import e_reporting


class UAEReportingSetting(Document):
    """Налаштування електронної звітності організації: провайдер, сертифікат КЕП. One per organization."""

    def validate(self):
        if self.provider not in e_reporting.PROVIDERS:
            frappe.throw(_("Невідомий провайдер {0}").format(self.provider))
        e_reporting.check_provider_allowed(self)
        if self.provider == e_reporting.IIT:
            e_reporting.validate_iit_setting(self)
        if self.certificate_valid_from and self.certificate_valid_to and getdate(self.certificate_valid_to) < getdate(self.certificate_valid_from):
            frappe.throw(_("Кінець строку дії сертифіката раніше за початок"))
