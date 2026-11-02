import frappe
from frappe import _

from ua_accounting.accounting import invoice
from ua_accounting.accounting.documents import TradeDocument


class UAPaymentInvoice(TradeDocument):
    """Інвойс (рахунок на оплату покупцю): the one document of a sale of goods and services (T-533).

    It does not post and does not touch the stock. Shipments, services, returns and tax invoices are
    separate posting documents made from it (accounting/invoice.py). Payments are in the finance documents.
    """

    doc_code = "PIN"
    doc_title = "Інвойс"
    posts = False

    def validate(self):
        super().validate()
        self.commercial_status = invoice.COMMERCIAL.get(self.docstatus, "Чернетка")
        if self.docstatus == 0:
            self.adjustments = []

    def on_submit(self):
        super().on_submit()
        invoice.refresh(self.name)

    def before_cancel(self):
        super().before_cancel()
        self.ignore_linked_doctypes = self.PAYMENT_LINKS
        events = []
        for doctype in (invoice.SALE, invoice.ACT, invoice.RETURN):
            events += frappe.get_all(doctype, filters={"invoice": self.name, "docstatus": 1}, pluck="name")
        if events:
            frappe.throw(
                _("Спочатку скасуйте або поверніть документи інвойсу: {0}").format(", ".join(events))
            )

    def on_cancel(self):
        super().on_cancel()
        invoice.refresh(self.name)

    # payments are not a link of the Invoice: an allocated payment stays and the Invoice cancels
    PAYMENT_LINKS = (
        "UA Cash Receipt",
        "UA Payment Allocation",
        "UA Bank Statement",
        "UA Bank Statement Line",
        "UA Tax Invoice",
    )
