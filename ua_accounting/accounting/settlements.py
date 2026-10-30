"""Settlements: dividends, tax payments, loans and interest, currency revaluation, opening balances."""

import calendar

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, get_first_day, getdate

from ua_accounting.accounting import ledger, opening
from ua_accounting.accounting.bank_cash import account_balance
from ua_accounting.accounting.documents import AccountingDocument, base_currency
from ua_accounting.accounting.utils import title_of
from ua_accounting.ua_catalogs.doctype.ua_currency.ua_currency import get_rate

TAX_PIT, TAX_MIL, TAX_ESV = "PIT", "MIL", "ESV"
# account of the tax payment by the tax type; the other taxes are on 641
TAX_ACCOUNT = {TAX_MIL: "642", TAX_ESV: "651"}

KIND_CREDIT, KIND_LOAN, KIND_AID = "Кредит банку", "Позика", "Поворотна фінансова допомога"
TERM_SHORT, TERM_LONG = "Короткостроковий", "Довгостроковий"


def check_bank_account(doc):
    bank = frappe.db.get_value("UA Bank Account", doc.bank_account, ["organization", "currency"], as_dict=True)
    if not bank or bank.organization != doc.organization:
        frappe.throw(_("Рахунок іншої організації"))
    if (bank.currency or base_currency()) != base_currency():
        frappe.throw(_("Потрібен рахунок у гривні"))


def month_end(date):
    date = getdate(date)
    return date.replace(day=calendar.monthrange(date.year, date.month)[1])


def check_month_end(doc):
    if getdate(doc.posting_date) != month_end(doc.posting_date):
        frappe.throw(_("Дата документа має бути останнім днем місяця"))


# ---------------------------------------------------------------- dividends


class UADividendAccrual(AccountingDocument):
    doc_code = "DV"
    doc_title = "Нарахування дивідендів"

    def validate(self):
        super().validate()
        if not self.founders:
            frappe.throw(_("Заповніть засновників"))
        for row in self.founders:
            if flt(row.amount) <= 0:
                frappe.throw(_("Рядок {0}: сума має бути більше нуля").format(row.idx))
            for rate in (row.pdfo_rate, row.vz_rate):
                if not 0 <= flt(rate) <= 100:
                    frappe.throw(_("Рядок {0}: ставка податку від 0 до 100 %").format(row.idx))
            row.pdfo = flt(flt(row.amount) * flt(row.pdfo_rate) / 100, 2)
            row.military_levy = flt(flt(row.amount) * flt(row.vz_rate) / 100, 2)
            row.net = flt(flt(row.amount) - row.pdfo - row.military_levy, 2)
        self.total_amount = flt(sum(flt(r.amount) for r in self.founders), 2)
        self.check_profit()

    def check_profit(self):
        """Dividends are paid from the retained profit (441), when the profit is accounted."""
        profit = -account_balance(self.organization, "441", self.posting_date)
        if profit <= 0:
            return
        used = account_balance(self.organization, "443", self.posting_date)
        if flt(self.total_amount) > flt(profit - used, 2):
            frappe.throw(_("Дивіденди перевищують нерозподілений прибуток"))

    def build(self):
        entries = []
        for row in self.founders:
            person = {"Person": row.founder}
            entries.append(self.entry("443", "671", row.amount, {}, person))
            if flt(row.pdfo):
                entries.append(self.entry("671", "641", row.pdfo, person, {"TaxType": TAX_PIT}))
            if flt(row.military_levy):
                entries.append(self.entry("671", "642", row.military_levy, person, {"TaxType": TAX_MIL}))
        return entries, [], []


# ---------------------------------------------------------------- tax payment


class UATaxPayment(AccountingDocument):
    doc_code = "TP"
    doc_title = "Сплата податків"

    def validate(self):
        super().validate()
        check_bank_account(self)
        if not self.rows:
            frappe.throw(_("Заповніть податки"))
        for row in self.rows:
            if flt(row.amount) <= 0:
                frappe.throw(_("Рядок {0}: сума має бути більше нуля").format(row.idx))
        self.total_amount = flt(sum(flt(r.amount) for r in self.rows), 2)

    def build(self):
        return [
            self.entry(TAX_ACCOUNT.get(row.tax_type, "641"), "311", row.amount, {"TaxType": row.tax_type},
                       {"BankAccount": self.bank_account})
            for row in self.rows
        ], [], []


# ---------------------------------------------------------------- loans


def loan_account(kind, term):
    """Account of the liability: Інструкція №291."""
    if kind == KIND_AID:
        return "685"
    if kind == KIND_CREDIT:
        return "601" if term == TERM_SHORT else "501"
    return "605" if term == TERM_SHORT else "505"


class UALoan(Document):
    def validate(self):
        if flt(self.principal) <= 0:
            frappe.throw(_("Сума має бути більше нуля"))
        if not 0 <= flt(self.annual_rate) <= 100:
            frappe.throw(_("Річна ставка від 0 до 100 %"))
        if self.end_date and getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(_("Дата погашення раніше дати початку"))
        contract = frappe.db.get_value(
            "UA Counterparty Contract", self.contract, ["counterparty", "organization", "contract_no"], as_dict=True)
        if not contract or contract.counterparty != self.lender:
            frappe.throw(_("Договір {0} не належить кредитору {1}").format(
                title_of("UA Counterparty Contract", self.contract), title_of("UA Counterparty", self.lender)))
        self.organization = contract.organization
        self.loan_title = f"{_(self.loan_kind)} {title_of('UA Counterparty', self.lender)} {contract.contract_no or ''}".strip()

    @property
    def account(self):
        return loan_account(self.loan_kind, self.term_kind)


def loan_of(doc):
    """Loan of a document, checked against the organization."""
    loan = frappe.get_cached_doc("UA Loan", doc.loan)
    if loan.organization != doc.organization:
        frappe.throw(_("Кредит належить іншій організації"))
    return loan


def loan_sum(table, field, loan, until=None, skip=None):
    """Sum of a field of the submitted rows of one loan."""
    sql = f"""select coalesce(sum({field}), 0) from `tab{table}` where loan = %s and docstatus = 1"""
    values = [loan]
    if until:
        sql += " and posting_date <= %s"
        values.append(getdate(until))
    if skip:
        sql += " and name != %s"
        values.append(skip)
    return flt(frappe.db.sql(sql, values)[0][0], 2)


def principal_balance(loan, until=None, skip=None):
    return flt(loan_sum("UA Loan Drawdown", "amount", loan, until, skip)
               - loan_sum("UA Loan Repayment", "principal_amount", loan, until, skip), 2)


def interest_accrued(loan, until=None, skip=None):
    sql = """select coalesce(sum(l.amount), 0) from `tabUA Loan Interest Line` l
        join `tabUA Loan Interest Accrual` a on a.name = l.parent and l.parenttype = 'UA Loan Interest Accrual'
        where l.loan = %s and a.docstatus = 1"""
    values = [loan]
    if until:
        sql += " and a.posting_date <= %s"
        values.append(getdate(until))
    if skip:
        sql += " and a.name != %s"
        values.append(skip)
    return flt(frappe.db.sql(sql, values)[0][0], 2)


def interest_paid(loan, until=None, skip=None):
    return loan_sum("UA Loan Repayment", "interest_amount", loan, until, skip)


def month_interest(loan, date):
    """Interest of the month of `date`: Σ balance of the day × rate / days of the year.

    The day of drawdown counts, the day of repayment does not (the balance is taken after the day's movements).
    """
    rate = flt(frappe.db.get_value("UA Loan", loan, "annual_rate"))
    if not rate:
        return 0.0
    last = month_end(date)
    first = get_first_day(last)
    moves = {}
    for table, field, sign in (("UA Loan Drawdown", "amount", 1), ("UA Loan Repayment", "principal_amount", -1)):
        for day, amount in frappe.db.sql(
            f"select posting_date, {field} from `tab{table}` where loan = %s and docstatus = 1 and posting_date <= %s",
            (loan, last),
        ):
            moves[day] = moves.get(day, 0) + sign * flt(amount)
    balance = sum(v for d, v in moves.items() if d < first)
    balance_days, day = 0.0, first
    while day <= last:
        balance += moves.get(day, 0)
        balance_days += balance
        day = add_days(day, 1)
    year_days = 366 if calendar.isleap(last.year) else 365
    return flt(balance_days * rate / 100 / year_days, 2)


class UALoanDrawdown(AccountingDocument):
    doc_code = "LD"
    doc_title = "Отримання кредиту / позики"

    def validate(self):
        super().validate()
        check_bank_account(self)
        loan = loan_of(self)
        if flt(self.amount) <= 0:
            frappe.throw(_("Сума має бути більше нуля"))
        drawn = loan_sum("UA Loan Drawdown", "amount", self.loan, skip=self.name)
        if flt(drawn + flt(self.amount), 2) > flt(loan.principal):
            frappe.throw(_("Загальна сума отримання перевищує суму за договором"))

    def build(self):
        loan = frappe.get_cached_doc("UA Loan", self.loan)
        return [self.entry("311", loan.account, self.amount, {"BankAccount": self.bank_account},
                           {"Counterparty": loan.lender, "Contract": loan.contract})], [], []


class UALoanInterestAccrual(AccountingDocument):
    doc_code = "LI"
    doc_title = "Нарахування відсотків за кредитами"

    def validate(self):
        super().validate()
        check_month_end(self)
        if not self.loans:
            frappe.throw(_("Заповніть кредити і позики"))
        seen = set()
        for row in self.loans:
            loan_of_row = frappe.db.get_value("UA Loan", row.loan, "organization")
            if loan_of_row != self.organization:
                frappe.throw(_("Рядок {0}: кредит належить іншій організації").format(row.idx))
            if row.loan in seen or self.accrued_in_month(row.loan):
                frappe.throw(_("Рядок {0}: відсотки за цей місяць уже нараховано").format(row.idx))
            seen.add(row.loan)
            row.amount = month_interest(row.loan, self.posting_date)
        self.total_amount = flt(sum(flt(r.amount) for r in self.loans), 2)

    def accrued_in_month(self, loan):
        first = get_first_day(self.posting_date)
        return frappe.db.sql(
            """select 1 from `tabUA Loan Interest Line` l join `tabUA Loan Interest Accrual` a on a.name = l.parent
            where l.loan = %s and a.docstatus = 1 and a.name != %s and a.posting_date between %s and %s limit 1""",
            (loan, self.name or "", first, month_end(self.posting_date)),
        )

    def build(self):
        entries = []
        for row in self.loans:
            loan = frappe.get_cached_doc("UA Loan", row.loan)
            entries.append(self.entry("951", "684", row.amount, {}, {"Counterparty": loan.lender, "Contract": loan.contract}))
        return entries, [], []


class UALoanRepayment(AccountingDocument):
    doc_code = "LR"
    doc_title = "Погашення кредиту / позики"

    def validate(self):
        super().validate()
        check_bank_account(self)
        loan_of(self)
        principal, interest = flt(self.principal_amount), flt(self.interest_amount)
        if principal < 0 or interest < 0 or not (principal or interest):
            frappe.throw(_("Вкажіть суму погашення"))
        if principal > principal_balance(self.loan, self.posting_date, self.name):
            frappe.throw(_("Сума погашення перевищує залишок кредиту"))
        # a backdated repayment must not push the total above the drawn principal
        if principal > principal_balance(self.loan, skip=self.name):
            frappe.throw(_("Сума погашення перевищує залишок кредиту"))
        due = interest_accrued(self.loan, self.posting_date) - interest_paid(self.loan, skip=self.name)
        if interest > flt(due, 2):
            frappe.throw(_("Сума відсотків перевищує нараховані відсотки"))

    def build(self):
        loan = frappe.get_cached_doc("UA Loan", self.loan)
        liability = {"Counterparty": loan.lender, "Contract": loan.contract}
        bank = {"BankAccount": self.bank_account}
        entries = []
        if flt(self.principal_amount):
            entries.append(self.entry(loan.account, "311", self.principal_amount, liability, bank))
        if flt(self.interest_amount):
            entries.append(self.entry("684", "311", self.interest_amount, liability, bank))
        return entries, [], []


# ---------------------------------------------------------------- currency revaluation

# account -> True for an asset (rate up is a gain), False for a liability
REVALUED = {"362": True, "312": True, "302": True, "632": False}


class UACurrencyRevaluation(AccountingDocument):
    doc_code = "RV"
    doc_title = "Переоцінка валютних розрахунків"

    def validate(self):
        super().validate()
        check_month_end(self)

    def balances(self):
        """Currency balances of the revalued accounts by account, subconto and currency."""
        accounts = list(REVALUED)
        rows = frappe.db.sql(
            f"""select account, subconto1, subconto2, currency, sum(debit) debit, sum(credit) credit,
            sum(currency_dr) currency_dr, sum(currency_cr) currency_cr from `tabUA Account Turnover`
            where organization = %s and period <= %s and currency != '' and account in ({', '.join(['%s'] * len(accounts))})
            group by account, subconto1, subconto2, currency order by account, subconto1, subconto2, currency""",
            (self.organization, get_first_day(self.posting_date), *accounts),
            as_dict=True,
        )
        ctx = {}
        for row in rows:
            acc = ledger._account(row.account, ctx)
            sub = {}
            for slot, kind in enumerate(acc.subconto[:2], start=1):
                if not kind.turnover_only and not kind.is_dynamic and row[f"subconto{slot}"]:
                    sub[kind.subconto_type] = row[f"subconto{slot}"]
            row.sub = sub
            yield row

    def build(self):
        entries = []
        for row in self.balances():
            rate = get_rate(row.currency, self.posting_date)
            if not rate:
                frappe.throw(_("Не задано курс валюти {0} на {1}").format(row.currency, self.posting_date))
            asset = REVALUED[row.account]
            old = flt(row.debit - row.credit if asset else row.credit - row.debit, 2)
            amount = flt(row.currency_dr - row.currency_cr if asset else row.currency_cr - row.currency_dr, 2)
            diff = flt(flt(amount * rate, 2) - old, 2)
            if not diff:
                continue
            cur = {"currency_dr": row.currency, "currency_cr": row.currency, "currency_amount_dr": 0, "currency_amount_cr": 0}
            if asset and diff > 0:
                entries.append(self.entry(row.account, "714", diff, row.sub, {}, **cur))
            elif asset:
                entries.append(self.entry("945", row.account, -diff, {}, row.sub, **cur))
            elif diff > 0:
                entries.append(self.entry("945", row.account, diff, {}, row.sub, **cur))
            else:
                entries.append(self.entry(row.account, "714", -diff, row.sub, {}, **cur))
        return entries, [], []


# ---------------------------------------------------------------- opening balances


class UAOpeningBalances(AccountingDocument):
    doc_code = "OB"
    doc_title = "Введення початкових залишків"

    def validate(self):
        super().validate()
        if not self.rows:
            frappe.throw(_("Заповніть залишки"))
        for row in self.rows:
            acc = opening.account_info(row.account)
            if not acc or opening.section_of(row.account) != row.section:
                frappe.throw(_("Рядок {0}: рахунок {1} не належить до розділу «{2}»").format(
                    row.idx, row.account, _(row.section)))
            if flt(row.amount) <= 0:
                frappe.throw(_("Рядок {0}: сума має бути більше нуля").format(row.idx))
            if flt(row.quantity) < 0:
                frappe.throw(_("Рядок {0}: кількість не може бути від'ємною").format(row.idx))
            if row.currency and row.currency != base_currency():
                if not acc.currency_accounting or flt(row.currency_amount) <= 0:
                    frappe.throw(_("Рядок {0}: вкажіть суму у валюті рахунку, що веде валютний облік").format(row.idx))
            opening.row_subconto(row, acc, row.section)
        self.total_amount = flt(sum(flt(r.amount) for r in self.rows), 2)

    def build(self):
        entries = []
        for row in self.rows:
            acc = opening.account_info(row.account)
            sub = opening.row_subconto(row, acc, row.section)
            debit = self.is_debit(row, acc)
            side = "dr" if debit else "cr"
            extra = {f"quantity_{side}": flt(row.quantity)}
            if row.currency and row.currency != base_currency():
                extra.update({f"currency_{side}": row.currency, f"currency_amount_{side}": flt(row.currency_amount)})
            tech = opening.TECHNICAL_ACCOUNT
            if debit:
                entries.append(self.entry(row.account, tech, row.amount, sub, {}, **extra))
            else:
                entries.append(self.entry(tech, row.account, row.amount, {}, sub, **extra))
        return entries, [], []

    @staticmethod
    def is_debit(row, acc):
        if acc.account_type == opening.ACTIVE:
            return True
        if acc.account_type == opening.PASSIVE:
            return False
        if row.balance_side:
            return row.balance_side == "Дебет"
        return row.account in opening.DEBIT_BY_DEFAULT
