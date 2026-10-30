import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import tax
from ua_accounting.accounting.documents import AccountingDocument, base_currency


class UATaxInvoice(AccountingDocument):
    """Податкова накладна. Posts no entries: it links the VAT registers of the basis document."""

    doc_code = "TI"
    doc_title = "Податкова накладна"
    posts = False

    def autoname(self):
        super().autoname()
        if not self.number:
            self.number = str(int(self.name.rsplit("-", 1)[-1]))

    def validate(self):
        super().validate()
        if not self.currency:
            self.currency = base_currency()
        if not self.lines:
            frappe.throw(_("Заповніть рядки податкової накладної"))
        if self.invoice_kind == tax.KIND_ORDINARY and not self.counterparty:
            frappe.throw(_("Вкажіть контрагента"))
        if self.contract:
            cp = frappe.db.get_value("UA Counterparty Contract", self.contract, "counterparty")
            if cp != self.counterparty:
                frappe.throw(_("Договір {0} не належить контрагенту {1}").format(self.contract, self.counterparty))
        self.calculate()
        self.registration_deadline = tax.deadline_of(self.posting_date)

    def calculate(self):
        base = vat_total = 0.0
        for row in self.lines:
            if not flt(row.base_amount) and flt(row.quantity) and flt(row.price):
                row.base_amount = flt(flt(row.quantity) * flt(row.price), 2)
            if flt(row.quantity) < 0 or flt(row.price) < 0:
                frappe.throw(_("Рядок {0}: кількість і ціна не можуть бути від'ємними").format(row.idx))
            base += flt(row.base_amount)
            vat_total += flt(row.vat_amount)
        self.total_base = flt(base, 2)
        self.total_vat = flt(vat_total, 2)
        self.total_amount = flt(base + vat_total, 2)

    def check_basis(self):
        """The basis must be a submitted document that matches this ПН; only then its VAT rows are linked."""
        if self.basis_type not in tax.BASIS_DIRECTION:
            frappe.throw(_("Для документа {0} податкова накладна не створюється").format(self.basis_type))
        basis = frappe.db.get_value(
            self.basis_type, self.basis, ["docstatus", "organization", "counterparty", "posting_date"], as_dict=True
        )
        if not basis or basis.docstatus != 1:
            frappe.throw(_("Документ-підстава {0} не проведений").format(self.basis))
        if basis.organization != self.organization:
            frappe.throw(_("Документ-підстава {0} належить іншій організації").format(self.basis))
        if tax.BASIS_DIRECTION[self.basis_type] != self.direction:
            frappe.throw(_("Напрямок податкової накладної не відповідає документу-підставі {0}").format(self.basis))
        if basis.counterparty != self.counterparty:
            frappe.throw(_("Контрагент податкової накладної не збігається з документом-підставою {0}").format(self.basis))
        if getdate(basis.posting_date) != getdate(self.posting_date):
            frappe.throw(_("Дата податкової накладної не збігається з документом-підставою {0}").format(self.basis))
        rows = frappe.get_all(
            tax.register_of(self.direction),
            filters={"registrar_type": self.basis_type, "registrar": self.basis, "event": ("!=", tax.EVENT_ADJUSTMENT)},
            fields=["base_amount", "vat_amount"],
            limit_page_length=0,
        )
        if not rows:
            frappe.throw(_("Документ {0} не має операцій, що оподатковуються ПДВ").format(self.basis))
        if flt(sum(r.base_amount for r in rows), 2) != flt(self.total_base, 2) or flt(sum(r.vat_amount for r in rows), 2) != flt(
            self.total_vat, 2
        ):
            frappe.throw(_("Суми податкової накладної не збігаються з регістром ПДВ документа {0}").format(self.basis))

    def before_submit(self):
        if self.invoice_kind == tax.KIND_ORDINARY and self.basis:
            self.check_basis()
            other = frappe.db.exists(
                "UA Tax Invoice",
                {
                    "basis_type": self.basis_type,
                    "basis": self.basis,
                    "invoice_kind": tax.KIND_ORDINARY,
                    "docstatus": 1,
                    "name": ("!=", self.name),
                },
            )
            if other:
                frappe.throw(_("Для документа {0} вже є податкова накладна {1}").format(self.basis, other))

    def on_submit(self):
        tax.link_registers(self)

    def before_cancel(self):
        if self.erpn_status == tax.STATUS_REGISTERED:
            frappe.throw(_("Зареєстровану в ЄРПН податкову накладну не скасовують: її виправляють розрахунком коригування"))
        rk = frappe.db.exists(tax.RK, {"tax_invoice": self.name, "docstatus": 1})
        if rk:
            frappe.throw(_("Спочатку скасуйте розрахунок коригування {0}").format(rk))

    def on_cancel(self):
        tax.unlink_registers(self.doctype, self.name)
