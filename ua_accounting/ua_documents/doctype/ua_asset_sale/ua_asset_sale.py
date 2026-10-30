import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import assets
from ua_accounting.accounting.asset_documents import AssetDocument
from ua_accounting.accounting.documents import EVENT_SHIPMENT, TAX_VAT, vat_info
from ua_accounting.accounting.utils import title_of

RECEIVABLE_ACCOUNT = "361"
INCOME_ACCOUNT = "712"
VAT_ACCOUNT = "641"
COST_ACCOUNT = "972"


class UAAssetSale(AssetDocument):
    """Продаж ОЗ.

    Dt 361 Ct 712   price with VAT
    Dt 712 Ct 641   VAT
    Dt 13x Ct 10x   wear
    Dt 972 Ct 10x   residual cost
    """

    doc_code = "PR"
    doc_title = "Продаж ОЗ"

    def validate(self):
        super().validate()
        self.check_contract()
        if flt(self.price) <= 0:
            frappe.throw(_("Ціна продажу має бути більше нуля"))
        self.check_not_depreciated_later()
        self.residual_value = self.residual_after_disposal()
        self.calculate_vat()

    def check_contract(self):
        contract = frappe.db.get_value(
            "UA Counterparty Contract", self.contract, ["counterparty", "organization"], as_dict=True
        )
        if not contract or contract.counterparty != self.counterparty:
            frappe.throw(
                _("Договір {0} не належить контрагенту {1}").format(
                    title_of("UA Counterparty Contract", self.contract), title_of("UA Counterparty", self.counterparty)
                )
            )
        if contract.organization != self.organization:
            frappe.throw(_("Договір {0} укладено з іншою організацією").format(title_of("UA Counterparty Contract", self.contract)))

    def calculate_vat(self):
        policy = self.accounting_policy
        payer = policy.vat_payer if policy else frappe.db.get_value("UA Organization", self.organization, "vat_payer")
        percent, taxable = vat_info(self.vat_rate, {})
        self.taxable = bool(payer and taxable)
        self.vat_amount = flt(flt(self.price) * percent / (100 + percent), 2) if self.taxable and percent else 0.0

    def build(self):
        price = flt(self.price, 2)
        settle = {
            "Counterparty": self.counterparty,
            "Contract": self.contract,
            "SettlementDoc": (self.doctype, self.name),
        }
        entries = [self.entry(RECEIVABLE_ACCOUNT, INCOME_ACCOUNT, price, settle, {})]
        if self.vat_amount:
            entries.append(self.entry(INCOME_ACCOUNT, VAT_ACCOUNT, self.vat_amount, {}, {"TaxType": TAX_VAT}))
        entries += self.disposal_entries(COST_ACCOUNT)
        liabilities = []
        if self.taxable:
            liabilities.append(self.vat_row(self.vat_rate, flt(price - self.vat_amount, 2), self.vat_amount, EVENT_SHIPMENT))
        return entries, liabilities, []
