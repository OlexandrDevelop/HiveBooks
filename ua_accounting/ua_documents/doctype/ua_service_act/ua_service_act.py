from frappe.utils import flt

from ua_accounting.accounting.documents import (
    EVENT_SHIPMENT,
    REVENUE_ACCOUNT,
    TAX_VAT,
    VAT_NONE,
    TradeDocument,
    allocate_advance,
    settlement_balance,
)

ADVANCE_ACCOUNT = "681"
VAT_ACCOUNT = "641"
VAT_PREPAID_ACCOUNT = "643"
VAT_DEDUCTION_ACCOUNT = "704"


class UAServiceAct(TradeDocument):
    """Надання послуг (акт виконаних робіт).

    Dt 361 Ct 703   revenue (with VAT)
    Dt 704 Ct 641   VAT liability
    Dt 681 Ct 361   offset of the advance
    Dt 704 Ct 643   VAT already taken at the advance (first event rule), instead of Ct 641
    """

    doc_code = "SAC"
    doc_title = "Надання послуг"

    def build(self):
        settle = "362" if self.is_foreign else "361"
        entries, liabilities = [], []
        groups = {}
        tax_sub = {"TaxType": TAX_VAT}
        vat_lines = []
        for row, _kind in self.lines():
            info = self.item_info(row.item)
            net, vat_amount, gross = self.row_amounts(row)
            self.add_group(groups, row, net, vat_amount, gross)
            item_sub = {"Item": row.item, "VatRate": row.vat_rate}
            entries.append(
                self.entry(
                    settle, REVENUE_ACCOUNT.get(info.item_type, "703"), gross, self.settle_sub, item_sub,
                    cur_amount=row.total,
                )
            )
            if vat_amount:
                vat_lines.append((row.vat_rate or "", vat_amount, item_sub))

        applied = 0.0
        alloc = {}
        gross_total = sum(g["gross"] for g in groups.values())
        if self.offset_advance and gross_total:
            balance = settlement_balance(
                self.organization, ADVANCE_ACCOUNT, self.counterparty, self.contract, "cr", self.posting_date,
                self._ctx,
            )
            applied = min(max(balance, 0), gross_total)
        if applied > 0:
            entries.append(
                self.entry(
                    ADVANCE_ACCOUNT, settle, applied, self.settle_sub, self.settle_sub,
                    cur_amount=flt(applied / self.exchange_rate, 2),
                )
            )
            alloc = allocate_advance(groups, applied, self.vat_mode)

        # the VAT of the advance part was recorded when the advance was paid: it is closed from 643
        covered_left = {key: covered_vat for key, (_part, covered_vat) in alloc.items()}
        for key, vat_amount, item_sub in vat_lines:
            from_advance = min(covered_left.get(key, 0), vat_amount)
            covered_left[key] = flt(covered_left.get(key, 0) - from_advance, 2)
            if from_advance:
                entries.append(self.entry(VAT_DEDUCTION_ACCOUNT, VAT_PREPAID_ACCOUNT, from_advance, item_sub, tax_sub))
            if flt(vat_amount - from_advance, 2):
                entries.append(
                    self.entry(VAT_DEDUCTION_ACCOUNT, VAT_ACCOUNT, flt(vat_amount - from_advance, 2), item_sub, tax_sub)
                )

        if self.vat_mode != VAT_NONE:
            for key, g in groups.items():
                covered, covered_vat = alloc.get(key, (0, 0))
                vat_left = flt(g["vat"] - covered_vat, 2)
                base_left = flt(g["net"] - (covered - covered_vat), 2)
                if g["taxable"] and (vat_left > 0 or base_left > 0):
                    liabilities.append(self.vat_row(key, base_left, vat_left, EVENT_SHIPMENT))
        return entries, liabilities, []
