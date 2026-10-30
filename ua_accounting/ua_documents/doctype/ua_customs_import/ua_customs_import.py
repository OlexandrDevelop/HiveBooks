import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting.documents import (
    EVENT_SHIPMENT,
    STOCK_ACCOUNT,
    TAX_VAT,
    TradeDocument,
    vat_info,
)

CUSTOMS_ACCOUNT = "377"
VAT_CREDIT_ACCOUNT = "644"


class UACustomsImport(TradeDocument):
    """Імпорт товарів з ВМД (митна декларація).

    Dt 281 Ct 632   customs value (price in the currency × the rate), the debt to the foreign supplier
    Dt 281 Ct 377   duty (мито), the debt to the customs
    Dt 644 Ct 377   import VAT = VAT rate × (customs value + duty)
    The payment to the customs is a cash payment "Інша витрата" with the account 377.
    """

    doc_code = "CIM"
    doc_title = "Імпорт товарів з ВМД"
    service_table = "no_services"

    def set_vat_mode(self):
        pass

    def validate_lines(self):
        super().validate_lines()
        if not 0 <= flt(self.duty_rate) <= 100:
            frappe.throw(_("Ставка мита має бути від 0 до 100 %"))
        for row in self.goods:
            if flt(row.price) < 0:
                frappe.throw(_("Рядок {0}: ціна не може бути від’ємною").format(row.idx))

    def figures(self, row):
        """(customs value, duty, VAT percent, import VAT) of a row in UAH."""
        value = flt(flt(row.quantity) * flt(row.price) * flt(self.exchange_rate), 2)
        duty = flt(value * flt(self.duty_rate) / 100, 2)
        percent, taxable = vat_info(row.vat_rate, self.__dict__.setdefault("_vat_cache", {}))
        percent = percent if taxable else 0
        return value, duty, percent, flt((value + duty) * percent / 100, 2)

    def calculate(self):
        value = duty = vat_total = 0.0
        for row in self.goods:
            v, d, _percent, vat_amount = self.figures(row)
            row.amount = flt(flt(row.quantity) * flt(row.price), 2)
            row.vat_amount = 0
            row.total = row.amount
            value += v
            duty += d
            vat_total += vat_amount
        self.customs_value = flt(value, 2)
        self.duty_amount = flt(duty, 2)
        self.import_vat = flt(vat_total, 2)
        self.total_amount = flt(value + duty + vat_total, 2)

    def build(self):
        self._ctx = {}
        settle = "632" if self.is_foreign else "631"
        customs_sub = {"Counterparty": self.customs, "Contract": self.customs_contract,
                       "SettlementDoc": (self.doctype, self.name)}
        tax_sub = {"TaxType": TAX_VAT}
        in_uah = {"currency_cr": "", "currency_amount_cr": 0}  # the debt to the customs is in hryvnias
        entries, credits = [], []
        groups = {}
        for row in self.goods:
            info = self.item_info(row.item)
            value, duty, percent, vat_amount = self.figures(row)
            stock = row.account or STOCK_ACCOUNT.get(info.item_type, "281")
            stock_sub = {"Item": row.item, "Warehouse": row.warehouse or self.warehouse}
            entries.append(
                self.entry(
                    stock, settle, value, stock_sub, self.settle_sub,
                    cur_amount=flt(flt(row.quantity) * flt(row.price), 2), quantity_dr=flt(row.quantity, 3),
                )
            )
            if duty:
                entries.append(self.entry(stock, CUSTOMS_ACCOUNT, duty, stock_sub, customs_sub, **in_uah))
            if vat_amount:
                entries.append(self.entry(VAT_CREDIT_ACCOUNT, CUSTOMS_ACCOUNT, vat_amount, tax_sub, customs_sub, **in_uah))
                g = groups.setdefault(row.vat_rate or "", [0.0, 0.0])
                g[0] = flt(g[0] + value + duty, 2)
                g[1] = flt(g[1] + vat_amount, 2)
        for key, (base, vat_amount) in groups.items():
            credits.append(self.vat_row(key, base, vat_amount, EVENT_SHIPMENT, counterparty=self.customs,
                                        contract=self.customs_contract))
        return entries, [], credits
