import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from ua_accounting.accounting import leases

# after a posted document these terms cannot change
LOCKED = (
    "organization",
    "lease_kind",
    "counterparty",
    "contract",
    "asset",
    "start_date",
    "end_date",
    "discount_rate",
    "fair_value",
    "asset_value",
    "monthly_rent",
    "vat_rate",
)


def same(a, b):
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        return flt(a) == flt(b)
    return str(a or "") == str(b or "")


def schedule_of(doc):
    return [(getdate(r.payment_date), flt(r.amount)) for r in doc.schedule]


class UALeaseAgreement(Document):
    """Договір оренди: operating lease (rent, off-balance 01) or finance lease with the payment schedule."""

    def validate(self):
        if self.organization and not frappe.db.exists("UA Organization", self.organization):
            frappe.throw(_("Організацію {0} не знайдено").format(self.organization))
        if getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(_("Кінець оренди раніше за початок"))
        if self.lease_kind == leases.OPERATING:
            if flt(self.monthly_rent) <= 0:
                frappe.throw(_("Орендна плата за місяць має бути більшою за нуль"))
            if flt(self.asset_value) < 0:
                frappe.throw(_("Вартість об'єкта не може бути від'ємною"))
            self.schedule = []
            self.present_value = self.recognised_value = self.effective_rate = 0
        else:
            self.validate_finance()
        self.check_contract()
        self.check_locked()

    def check_contract(self):
        row = frappe.db.get_value("UA Counterparty Contract", self.contract, ["counterparty", "organization"], as_dict=True)
        if not row or row.counterparty != self.counterparty or (row.organization and row.organization != self.organization):
            frappe.throw(_("Договір {0} не підходить до орендодавця й організації").format(self.contract))

    def validate_finance(self):
        if not self.schedule:
            frappe.throw(_("Заповніть графік лізингових платежів"))
        if not 0 <= flt(self.discount_rate) <= 100:
            frappe.throw(_("Ставка дисконтування має бути від 0 до 100 %"))
        if flt(self.fair_value) < 0:
            frappe.throw(_("Справедлива вартість не може бути від'ємною"))
        seen = set()
        for r in self.schedule:
            if flt(r.amount) <= 0:
                frappe.throw(_("Рядок {0}: сума платежу має бути більшою за нуль").format(r.idx))
            if getdate(r.payment_date) <= getdate(self.start_date):
                frappe.throw(_("Рядок {0}: дата платежу має бути після початку оренди").format(r.idx))
            if getdate(r.payment_date) in seen:
                frappe.throw(_("Рядок {0}: дата платежу повторюється").format(r.idx))
            seen.add(getdate(r.payment_date))
        self.monthly_rent = self.asset_value = 0
        leases.calculate_schedule(self)

    def check_locked(self):
        if self.is_new() or not leases.used_by_documents(self.name):
            return
        old = self.get_doc_before_save()
        if not old:
            return
        changed = any(not same(self.get(f), old.get(f)) for f in LOCKED)
        if changed or schedule_of(self) != schedule_of(old):
            frappe.throw(_("Є проведені документи за договором: основні умови змінювати не можна"))

    def on_trash(self):
        if leases.used_by_documents(self.name):
            frappe.throw(_("За договором є проведені документи"))
