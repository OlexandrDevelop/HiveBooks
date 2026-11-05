import frappe
from frappe import _
from frappe.beeone.registers.posting import Moment
from frappe.utils import flt, get_datetime, getdate

from ua_accounting.accounting import invoice, invoice_events
from ua_accounting.accounting.documents import TradeDocument

EVENT_CHANGEABLE = ("status", "cancelled_on", "cancelled_by", "cancel_reason", "cost_amount")
LINE_CHANGEABLE = ("cost",)


class UAPaymentInvoice(TradeDocument):
    """Інвойс: the one document of a sale of goods and services (T-533, T-705).

    The Invoice is the sale. There is no document of the shipment, of the service provision or of the return: they are
    events of the Invoice, rows of `events` with their lines in `event_lines`, each with its own number, date, warehouse,
    status and movements (accounting/invoice_events.py). The Invoice is the registrar of the movements of all its
    events, and the event number is the part of the record sets. The rows are added only by the actions of
    api/invoice.py; a posted event is cancelled, never edited. Tax invoices are made per event or for an advance.
    Payments stay in the finance documents.
    """

    doc_code = "PIN"
    doc_title = "Інвойс"
    posts = False
    # the entries of the sequence of the stock cost are the events, not the Invoice
    sequence_by_parts = True

    def validate(self):
        super().validate()
        self.commercial_status = invoice.COMMERCIAL.get(self.docstatus, "Чернетка")
        if self.docstatus == 0 and self.customer_order and frappe.db.get_value("UA Customer Order", self.customer_order, "docstatus") == 2:
            frappe.throw(_("Замовлення {0} скасоване").format(self.customer_order))
        if self.docstatus == 0:
            self.adjustments = []
            self.events = []
            self.event_lines = []

    def before_update_after_submit(self):
        self.check_events_unchanged()

    def check_events_unchanged(self):
        """The events change only through the actions of the Invoice, and then only their status and cost."""
        old = self.get_doc_before_save()
        if not old:
            return
        action = self.flags.get("invoice_action")
        for table, changeable in (("events", EVENT_CHANGEABLE), ("event_lines", LINE_CHANGEABLE)):
            before = {r.name: r for r in old.get(table) or []}
            after = {r.name: r for r in self.get(table) or [] if not r.is_new()}
            if set(before) - set(after):
                frappe.throw(_("Подію інвойсу не можна видалити: її скасовують"))
            for name, row in after.items():
                for df in row.meta.fields:
                    if df.fieldname in changeable or df.fieldtype in ("Section Break", "Column Break"):
                        continue
                    if _norm(row.get(df.fieldname)) != _norm(before[name].get(df.fieldname)):
                        frappe.throw(_("Подію інвойсу не можна змінити: її скасовують"))
            if any(r.is_new() for r in self.get(table) or []) and not action:
                frappe.throw(_("Події додають діями інвойсу: відвантаження, надання послуг, повернення"))

    def on_submit(self):
        super().on_submit()
        self.refresh_states()

    def before_cancel(self):
        super().before_cancel()
        self.ignore_linked_doctypes = self.PAYMENT_LINKS
        # the posted events are cancelled with the Invoice, the last one first (visible in the history)
        invoice_events.cancel_all(self, _("Скасування інвойсу"))

    def on_cancel(self):
        super().on_cancel()
        self.refresh_states()

    def refresh_states(self):
        invoice.refresh(self.name)
        invoice.refresh_contract(self.organization, self.counterparty, self.contract)
        if self.customer_order:
            invoice.set_order_status(self.customer_order)

    # ------------------------------------------------------------ sequence of the stock cost: the parts are the events

    def get_sequence_keys(self, sequence):
        return [(self.organization,)]

    def get_sequence_parts(self, sequence):
        """[(event number, moment)] of the posted events (rebuild of the sequence)."""
        return [
            (e.number, Moment(getdate(e.posting_date), 0, get_datetime(e.moment), self.name))
            for e in invoice.posted_events(self).values()
        ]

    def repost_part_in_sequence(self, part, sequence=None):
        invoice_events.repost_event(self, invoice_events.get_event(self, part))

    # payments are not a link of the Invoice: an allocated payment stays and the Invoice cancels
    PAYMENT_LINKS = (
        "UA Cash Receipt",
        "UA Payment Allocation",
        "UA Bank Statement",
        "UA Bank Statement Line",
        "UA Tax Invoice",
    )


def _norm(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    return str(value)
