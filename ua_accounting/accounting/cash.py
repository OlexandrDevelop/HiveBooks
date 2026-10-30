"""Base of the cash documents: Надходження коштів and Витрата коштів."""

import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting.documents import (
    AccountingDocument,
    base_currency,
    vat_info,
)
from ua_accounting.accounting.utils import title_of

BANK = "Банк"
CASH = "Каса"
OTHER_SUBCONTO = ("Person", "ExpenseItem", "Department")


class CashDocument(AccountingDocument):
    """Common header: cash type, bank account or cash desk, amount, currency."""

    def validate(self):
        super().validate()
        self.set_currency()
        self.check_cash_side()
        self.check_counterparty_fields()
        self.calculate_vat()

    def set_currency(self):
        if not self.currency:
            self.currency = base_currency()
        if self.currency == base_currency():
            self.exchange_rate = 1
        elif not flt(self.exchange_rate) or (self.is_new() and flt(self.exchange_rate) == 1):
            # 1 is the field default: for a foreign currency it is not a real rate
            from ua_accounting.ua_catalogs.doctype.ua_currency.ua_currency import get_rate

            self.exchange_rate = get_rate(self.currency, self.posting_date)
        if not flt(self.exchange_rate):
            frappe.throw(_("Не задано курс валюти {0} на {1}").format(self.currency, self.posting_date))
        if flt(self.amount) <= 0:
            frappe.throw(_("Сума має бути більше нуля"))

    def check_cash_side(self):
        if self.cash_type == BANK:
            if not self.bank_account:
                frappe.throw(_("Вкажіть банківський рахунок"))
            self.cash_desk = None
            row = frappe.db.get_value(
                "UA Bank Account", self.bank_account, ["organization", "currency"], as_dict=True
            )
            owner, currency = row.organization, row.currency
        else:
            if not self.cash_desk:
                frappe.throw(_("Вкажіть касу"))
            self.bank_account = None
            row = frappe.db.get_value("UA Cash Desk", self.cash_desk, ["organization", "currency"], as_dict=True)
            owner, currency = row.organization, row.currency
        if owner != self.organization:
            frappe.throw(_("Рахунок або каса належить іншій організації"))
        if currency and currency != self.currency:
            frappe.throw(_("Валюта документа {0} не збігається з валютою {1}").format(self.currency, currency))

    def check_counterparty_fields(self):
        if self.is_settlement():
            if not self.counterparty:
                frappe.throw(_("Вкажіть контрагента"))
            if self.contract:
                cp = frappe.db.get_value("UA Counterparty Contract", self.contract, "counterparty")
                if cp != self.counterparty:
                    frappe.throw(
                        _("Договір {0} не належить контрагенту {1}").format(
                            title_of("UA Counterparty Contract", self.contract),
                            title_of("UA Counterparty", self.counterparty),
                        )
                    )
        elif self.operation_type in ("Отримання від підзвітної особи", "Видача підзвітній особі"):
            if not self.person:
                frappe.throw(_("Вкажіть підзвітну особу"))
        else:
            if self.operation_type in ("Повернення від постачальника", "Повернення покупцю"):
                if not self.counterparty:
                    frappe.throw(_("Вкажіть контрагента"))
                return
            if not self.other_account:
                frappe.throw(_("Вкажіть рахунок кореспонденції"))
            acc = frappe.db.get_value("UA Account", self.other_account, ["is_group", "off_balance"], as_dict=True)
            if acc.is_group or acc.off_balance:
                frappe.throw(_("Рахунок {0} не підходить для обліку").format(self.other_account))

    def calculate_vat(self):
        """VAT is counted only for an advance: VAT in the amount, by the rate."""
        self.vat_amount = 0
        if self.is_settlement() and self.is_advance() and self.vat_rate:
            percent, taxable = vat_info(self.vat_rate, {})
            if taxable and percent:
                self.vat_amount = flt(flt(self.amount) * percent / (100 + percent), 2)

    # to be set in the subclass
    def is_settlement(self):
        raise NotImplementedError

    def is_advance(self):
        raise NotImplementedError

    # ------------------------------------------------------------ builders

    @property
    def is_foreign(self):
        return self.currency != base_currency()

    @property
    def cash_account(self):
        if self.cash_type == BANK:
            return "312" if self.is_foreign else "311"
        return "302" if self.is_foreign else "301"

    @property
    def cash_sub(self):
        sub = {"CashFlowItem": self.cash_flow_item}
        if self.cash_type == BANK:
            sub["BankAccount"] = self.bank_account
        else:
            sub["CashDesk"] = self.cash_desk
        return sub

    @property
    def other_sub(self):
        return {
            "Counterparty": self.counterparty,
            "Contract": self.contract,
            "SettlementDoc": (self.doctype, self.name),
            "CashFlowItem": self.cash_flow_item,
            "Person": self.person,
            "ExpenseItem": self.expense_item,
            "Department": self.department,
            "TaxType": self.get("tax_type"),
        }

    @property
    def settle_sub(self):
        return {
            "Counterparty": self.counterparty,
            "Contract": self.contract,
            "SettlementDoc": (self.doctype, self.name),
        }

    @property
    def amount_uah(self):
        return flt(flt(self.amount) * flt(self.exchange_rate), 2)

    @property
    def vat_uah(self):
        return flt(flt(self.vat_amount) * flt(self.exchange_rate), 2)
