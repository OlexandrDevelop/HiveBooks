import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import ledger, tax, vat
from ua_accounting.accounting.documents import TAX_VAT, AccountingDocument

VAT_ACCOUNT = "641"
CREDIT_ACCOUNT = "644"
DEDUCTION_ACCOUNT = "704"


class UATaxAdjustment(AccountingDocument):
    """Розрахунок коригування до податкової накладної.

    Issued, decrease:   Dt 641 Ct 704   (positive amounts, no storno)
    Issued, increase:   Dt 704 Ct 641
    Received, decrease: Dt 644 Ct 641
    Received, increase: Dt 641 Ct 644
    """

    doc_code = "TA"
    doc_title = "Розрахунок коригування"

    def autoname(self):
        super().autoname()
        if not self.number:
            self.number = str(int(self.name.rsplit("-", 1)[-1]))

    def validate(self):
        super().validate()
        pn = frappe.db.get_value(
            tax.PN,
            self.tax_invoice,
            ["docstatus", "posting_date", "direction", "counterparty", "contract", "organization", "basis_type", "basis"],
            as_dict=True,
        )
        if not pn or pn.docstatus != 1:
            frappe.throw(_("Податкова накладна {0} не проведена").format(self.tax_invoice))
        if pn.organization != self.organization:
            frappe.throw(_("Податкова накладна належить іншій організації"))
        self.direction = pn.direction
        self.counterparty = pn.counterparty
        self.contract = pn.contract
        if getdate(self.posting_date) < getdate(pn.posting_date):
            frappe.throw(_("Розрахунок коригування не може бути раніше за податкову накладну"))
        if not self.lines:
            frappe.throw(_("Заповніть рядки розрахунку коригування"))
        self._pn = pn
        self.calculate()

    def calculate(self):
        total_base = total_vat = 0.0
        for row in self.lines:
            for f in ("quantity_after", "base_after", "vat_after"):
                if flt(row.get(f)) < 0:
                    frappe.throw(_("Рядок {0}: значення після коригування не може бути від'ємним").format(row.idx))
            row.delta_base = flt(flt(row.base_after) - flt(row.base_before), 2)
            row.delta_vat = flt(flt(row.vat_after) - flt(row.vat_before), 2)
            total_base += row.delta_base
            total_vat += row.delta_vat
        self.total_delta_base = flt(total_base, 2)
        self.total_delta_vat = flt(total_vat, 2)

    def before_submit(self):
        pn = frappe.get_doc(tax.PN, self.tax_invoice)
        state = tax.effective_lines(pn, exclude=self.name)
        if len(state) != len(self.lines):
            frappe.throw(_("Рядки розрахунку коригування не відповідають податковій накладній {0}").format(pn.name))
        for row, s in zip(self.lines, state):
            if flt(row.base_before, 2) != flt(s["base"], 2) or flt(row.vat_before, 2) != flt(s["vat"], 2):
                frappe.throw(
                    _("Рядок {0}: суми «до коригування» не збігаються з поточним станом накладної ({1} / {2}). Створіть розрахунок заново").format(
                        row.idx, s["base"], s["vat"]
                    )
                )
        if not any(row.delta_base or row.delta_vat for row in self.lines):
            frappe.throw(_("У розрахунку коригування немає змін"))

    def on_submit(self):
        self._ctx = {}
        issued = self.direction == tax.ISSUED
        entries, rows = [], []
        for row in self.lines:
            if not row.vat_rate:
                frappe.throw(_("Рядок {0}: вкажіть ставку ПДВ").format(row.idx))
            delta = flt(row.delta_vat, 2)
            if delta:
                entries.append(self.make_entry(row, delta, issued))
            rows.append(
                self.vat_row(
                    row.vat_rate,
                    row.delta_base,
                    delta,
                    tax.EVENT_ADJUSTMENT,
                    settlement_doc_type=self._pn.basis_type or "",
                    settlement_doc=self._pn.basis or "",
                    tax_invoice_type=self.doctype,
                    tax_invoice=self.name,
                )
            )
        ledger.post_entries(self, entries)
        vat.post_vat_entries(self, rows if issued else (), () if issued else rows)

    def make_entry(self, row, delta, issued):
        amount = abs(delta)
        tax_sub = {"TaxType": TAX_VAT}
        item_sub = {"VatRate": row.vat_rate}
        decrease = delta < 0
        if issued:
            dr, cr = (VAT_ACCOUNT, DEDUCTION_ACCOUNT) if decrease else (DEDUCTION_ACCOUNT, VAT_ACCOUNT)
        else:
            dr, cr = (CREDIT_ACCOUNT, VAT_ACCOUNT) if decrease else (VAT_ACCOUNT, CREDIT_ACCOUNT)
        sub = {VAT_ACCOUNT: tax_sub, CREDIT_ACCOUNT: tax_sub, DEDUCTION_ACCOUNT: item_sub}
        return self.entry(dr, cr, amount, sub[dr], sub[cr], content=self.content_text())

    def before_cancel(self):
        if self.erpn_status == tax.STATUS_REGISTERED:
            frappe.throw(_("Зареєстрований в ЄРПН розрахунок коригування не скасовують"))
