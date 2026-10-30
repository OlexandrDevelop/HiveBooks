"""Posting behavior for bank, accountable expenses, payroll cash and exchange."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.bank_cash import account_balance, check_cash_balance, has_currency_entries
from ua_accounting.accounting.documents import AccountingDocument, TAX_VAT, vat_info
from ua_accounting.ua_catalogs.doctype.ua_currency.ua_currency import get_rate


class UAPaymentOrder(AccountingDocument):
    doc_code = "PO"
    doc_title = "Платіжне доручення"
    posts = False

    def validate(self):
        super().validate()
        if flt(self.amount) <= 0:
            frappe.throw(_("Сума має бути більше нуля"))
        if frappe.db.get_value("UA Bank Account", self.bank_account, "organization") != self.organization:
            frappe.throw(_("Рахунок іншої організації"))
        if (self.payment_kind or "Постачальнику") == "Постачальнику" and not self.counterparty:
            frappe.throw(_("Вкажіть контрагента"))
        if self.recipient_iban:
            self.recipient_iban = self.recipient_iban.replace(" ", "").upper()
            if not valid_ua_iban(self.recipient_iban):
                frappe.throw(_("IBAN отримувача {0} неправильний").format(self.recipient_iban))
        if len(self.purpose or "") > PURPOSE_LIMIT:
            frappe.throw(_("Призначення платежу довше {0} символів").format(PURPOSE_LIMIT))
        if not self.number:
            self.number = next_number(self)
        paid = frappe.db.sql(
            """select 1 from `tabUA Bank Statement Line` l join `tabUA Bank Statement` s on s.name=l.parent
            where l.payment_order=%s and s.docstatus=1 limit 1""", self.name or "")
        if paid:
            self.status = "Сплачено"
        elif self.status not in ("Експортовано", "Оплачено"):
            self.status = "Створено"


PURPOSE_LIMIT = 160


def valid_ua_iban(iban):
    """IBAN of Ukraine: UA + 2 check digits + 25 digits, ISO 13616 (remainder 1 after mod 97)."""
    if len(iban) != 29 or not iban.startswith("UA") or not iban[2:].isdigit():
        return False
    moved = iban[4:] + iban[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def next_number(doc):
    """Number of the order per organization and year: the last number plus one, like in 1C."""
    year = getdate(doc.posting_date).year
    last = frappe.db.sql(
        """select max(cast(number as unsigned)) from `tabUA Payment Order`
        where organization = %s and year(posting_date) = %s""", (doc.organization, year))[0][0]
    return str(int(last or 0) + 1)


# operation type -> the only direction it can have in a statement line
DIRECTION_OF = {"Оплата від покупця": "Надходження", "Оплата постачальнику": "Списання",
                "Отримання кредиту": "Надходження", "Отримання від підзвітної особи": "Надходження",
                "Видача підзвітній особі": "Списання", "Перерахування податків": "Списання"}


class UABankStatement(AccountingDocument):
    doc_code = "BS"
    doc_title = "Банківська виписка"

    def validate(self):
        super().validate()
        bank = frappe.db.get_value("UA Bank Account", self.bank_account, ["organization", "currency"], as_dict=True)
        if not bank or bank.organization != self.organization:
            frappe.throw(_("Рахунок іншої організації"))
        self.currency = bank.currency or "UAH"
        self.exchange_rate = 1 if self.currency == "UAH" else flt(self.exchange_rate) or get_rate(self.currency, self.posting_date)
        if self.get("format"):
            return  # a statement loaded from a file (T-446): its lines are posted by the exchange method, not by this document
        if not self.lines:
            frappe.throw(_("Заповніть операції виписки"))
        if frappe.db.exists(self.doctype, {"bank_account": self.bank_account, "posting_date": self.posting_date,
                                           "docstatus": 1, "name": ("!=", self.name or "")}):
            frappe.throw(_("Виписка за цю дату вже проведена"))
        seen_orders = set()
        for row in self.lines:
            if flt(row.amount) <= 0:
                frappe.throw(_("Сума має бути більше нуля"))
            if row.operation_type in ("Оплата від покупця", "Оплата постачальнику") and not row.counterparty:
                frappe.throw(_("Вкажіть контрагента"))
            expected = DIRECTION_OF.get(row.operation_type)
            if expected and row.direction != expected:
                frappe.throw(_("Операція «{0}» має напрямок «{1}», а в рядку «{2}»").format(
                    row.operation_type, expected, row.direction))
            if row.payment_order:
                order = frappe.db.get_value("UA Payment Order", row.payment_order,
                                            ["organization", "bank_account", "amount", "docstatus"], as_dict=True)
                if not order or order.organization != self.organization or order.bank_account != self.bank_account or order.docstatus != 1 or flt(order.amount) != flt(row.amount):
                    frappe.throw(_("Платіжне доручення не відповідає виписці"))
                if row.payment_order in seen_orders or self.order_is_paid(row.payment_order):
                    frappe.throw(_("Платіжне доручення {0} вже сплачене").format(row.payment_order))
                seen_orders.add(row.payment_order)
        self.update_balances()

    def order_is_paid(self, order):
        """True when another posted statement already pays the order."""
        return bool(frappe.db.sql(
            """select 1 from `tabUA Bank Statement Line` l join `tabUA Bank Statement` s on s.name=l.parent
            where l.payment_order=%s and s.docstatus=1 and s.name!=%s limit 1""", (order, self.name or "")))

    def update_balances(self):
        account = "312" if self.currency != "UAH" else "311"
        self.opening_balance = account_balance(self.organization, account, self.posting_date, "BankAccount", self.bank_account, before=True)
        movement = sum(flt(row.amount) * (1 if row.direction == "Надходження" else -1) for row in self.lines)
        self.closing_balance = flt(self.opening_balance + movement * flt(self.exchange_rate), 2)

    def build(self):
        bank_account = "312" if self.currency != "UAH" else "311"
        entries = []
        for row in self.lines:
            other = {"Оплата від покупця": "362" if self.currency != "UAH" else "361",
                     "Оплата постачальнику": "632" if self.currency != "UAH" else "631",
                     "Отримання кредиту": "601", "Отримання від підзвітної особи": "372",
                     "Видача підзвітній особі": "372", "Перерахування податків": "641"}.get(row.operation_type, row.other_account)
            if not other:
                frappe.throw(_("Вкажіть рахунок кореспонденції"))
            incoming = row.direction == "Надходження"
            bank_sub = {"BankAccount": self.bank_account, "CashFlowItem": row.cash_flow_item}
            other_sub = {"Counterparty": row.counterparty, "Contract": row.contract, "Person": row.person}
            entries.append(self.entry(bank_account if incoming else other, other if incoming else bank_account,
                                      flt(flt(row.amount) * flt(self.exchange_rate), 2),
                                      bank_sub if incoming else other_sub, other_sub if incoming else bank_sub,
                                      cur_amount=row.amount))
        return entries, [], []

    def before_submit(self):
        if self.get("format"):
            frappe.throw(_("Виписку з файлу не проводять: документи створює обмін даними"))

    def on_submit(self):
        super().on_submit()
        self.update_orders("Сплачено")
        self.refresh_later()

    def on_cancel(self):
        super().on_cancel()
        self.update_orders("Створено")
        self.refresh_later()

    def update_orders(self, status):
        for row in self.lines:
            if row.payment_order:
                frappe.db.set_value("UA Payment Order", row.payment_order, "status", status, update_modified=False)

    def refresh_later(self):
        for name in frappe.get_all(self.doctype, filters={"bank_account": self.bank_account,
                                                           "posting_date": (">", self.posting_date), "docstatus": 1},
                                   pluck="name", order_by="posting_date asc"):
            doc = frappe.get_doc(self.doctype, name)
            doc.update_balances()
            frappe.db.set_value(self.doctype, name, {"opening_balance": doc.opening_balance,
                                                     "closing_balance": doc.closing_balance}, update_modified=False)


class UAAdvanceReport(AccountingDocument):
    """Авансовий звіт.

    A row has the gross amount (`amount_gross` or `amount`) and the VAT (counted by `vat_rate`, or stated in `vat_amount`).
    VAT without a tax invoice waits on 644 (Дт 644 Кт 372); with the tax invoice it is confirmed (Дт 641 Кт 644).
    A row without VAT goes to cost in full.
    """

    doc_code = "AR"
    doc_title = "Авансовий звіт"

    def validate(self):
        super().validate()
        if not self.person or not self.expenses:
            frappe.throw(_("Вкажіть підзвітну особу та витрати"))
        cache = {}
        policy = self.accounting_policy
        payer = policy.vat_payer if policy else frappe.db.get_value("UA Organization", self.organization, "vat_payer")
        for row in self.expenses:
            self.fill_row(row, cache)
            if not payer:
                row.vat_amount = 0  # no tax credit: the whole amount goes to cost
            if flt(row.amount) <= 0:
                frappe.throw(_("Сума витрати має бути більше нуля"))
            if flt(row.vat_amount) > flt(row.amount):
                frappe.throw(_("ПДВ не може бути більше суми витрати"))
            if not (row.item or row.expense_account):
                frappe.throw(_("У рядку {0} вкажіть номенклатуру або рахунок витрат").format(row.idx))
            if row.item and (not row.warehouse or flt(row.quantity) <= 0):
                frappe.throw(_("Вкажіть кількість та склад"))
            acc = row.expense_account and frappe.db.get_value(
                "UA Account", row.expense_account, ["is_group", "off_balance"], as_dict=True
            )
            if row.expense_account and (not acc or acc.is_group or acc.off_balance):
                frappe.throw(_("Рядок {0}: рахунок {1} не підходить для обліку").format(row.idx, row.expense_account))
        self.total_amount = flt(sum(flt(row.amount) for row in self.expenses), 2)

    @staticmethod
    def fill_row(row, cache):
        """`account` and `amount_gross` are the same as `expense_account` and `amount`. VAT is counted by the rate."""
        row.expense_account = row.account or row.expense_account
        if flt(row.amount_gross):
            row.amount = flt(row.amount_gross, 2)
        if not flt(row.vat_amount):
            percent, taxable = vat_info(row.vat_rate, cache)
            row.vat_amount = flt(row.amount * percent / (100 + percent), 2) if taxable and percent else 0

    def build(self):
        entries = []
        for row in self.expenses:
            vat = flt(row.vat_amount)
            cost = flt(flt(row.amount) - vat, 2)
            sub = {"Item": row.item, "Warehouse": row.warehouse, "ExpenseItem": row.expense_item,
                   "Counterparty": row.counterparty, "Department": row.department}
            entry = self.entry(row.expense_account or ("281" if row.item else None), "372", cost, sub, {"Person": self.person})
            if row.item:
                entry["quantity_dr"] = flt(row.quantity)
            entries.append(entry)
            if vat:
                entries.append(self.entry("644", "372", vat, {"TaxType": TAX_VAT}, {"Person": self.person}))
                if row.tax_invoice:
                    entries.append(self.entry("641", "644", vat, {"TaxType": TAX_VAT}, {"TaxType": TAX_VAT}))
        return entries, [], []


class UACashDisbursement(AccountingDocument):
    doc_code = "CD"
    doc_title = "Видаткова відомість"

    def validate(self):
        super().validate()
        if frappe.db.get_value("UA Cash Desk", self.cash_desk, "organization") != self.organization:
            frappe.throw(_("Каса іншої організації"))
        if not self.lines:
            frappe.throw(_("Заповніть одержувачів"))
        for row in self.lines:
            if not row.person or flt(row.amount) <= 0:
                frappe.throw(_("Вкажіть одержувача та суму"))
        self.total_amount = flt(sum(flt(row.amount) for row in self.lines), 2)

    def on_submit(self):
        check_cash_balance(self.organization, self.cash_desk, self.posting_date, -flt(self.total_amount))
        super().on_submit()

    def build(self):
        return [self.entry("661", "301", row.amount, {"Person": row.person}, {"CashDesk": self.cash_desk})
                for row in self.lines], [], []


class UACurrencyExchange(AccountingDocument):
    doc_code = "FX"
    doc_title = "Купівля/продаж валюти"

    def validate(self):
        super().validate()
        for field, currency in (("uah_bank_account", "UAH"), ("currency_bank_account", self.currency)):
            row = frappe.db.get_value("UA Bank Account", self.get(field), ["organization", "currency"], as_dict=True)
            if not row or row.organization != self.organization or row.currency != currency:
                frappe.throw(_("Валюта банківського рахунку не збігається з документом"))
        if flt(self.currency_amount) <= 0 or flt(self.deal_rate) <= 0:
            frappe.throw(_("Сума і курс мають бути більше нуля"))
        self.official_rate = flt(self.official_rate) or get_rate(self.currency, self.posting_date)
        if not flt(self.official_rate):
            frappe.throw(_("Не задано курс НБУ"))
        if self.operation_type == "Продаж валюти":
            args = (self.organization, "312", self.posting_date, "BankAccount", self.currency_bank_account)
            available = account_balance(*args, in_currency=True)
            if not has_currency_entries(*args):  # the ledger holds no foreign-currency quantity (balance entered in UAH only)
                available = flt(account_balance(*args) / flt(self.official_rate), 2)
            if available < flt(self.currency_amount):
                frappe.throw(_("Недостатньо валюти на рахунку"))

    def build(self):
        official = flt(flt(self.currency_amount) * flt(self.official_rate), 2)
        deal = flt(flt(self.currency_amount) * flt(self.deal_rate), 2)
        uah = {"BankAccount": self.uah_bank_account}
        foreign = {"BankAccount": self.currency_bank_account}
        if self.operation_type == "Купівля валюти":
            entries = [self.entry("333", "311", deal, {}, uah),
                       self.entry("312", "333", official, foreign, {},
                                  currency_dr=self.currency, currency_amount_dr=self.currency_amount)]
            diff = flt(deal - official, 2)
            if diff > 0:
                entries.append(self.entry("945", "333", diff))
            elif diff < 0:
                entries.append(self.entry("333", "714", -diff))
        else:
            entries = [self.entry("333", "312", official, {}, foreign,
                                  currency_cr=self.currency, currency_amount_cr=self.currency_amount),
                       self.entry("311", "333", deal, uah, {})]
            diff = flt(deal - official, 2)
            if diff > 0:
                entries.append(self.entry("333", "714", diff))
            elif diff < 0:
                entries.append(self.entry("945", "333", -diff))
        return entries, [], []
