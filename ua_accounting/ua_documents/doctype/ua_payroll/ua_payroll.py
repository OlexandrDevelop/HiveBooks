import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate

from ua_accounting.accounting import payroll as calc
from ua_accounting.accounting import provisions as prov
from ua_accounting.accounting.documents import AccountingDocument

DEFAULT_EXPENSE_ACCOUNT = "92"
LIABILITY = "661"
FSS = "663"
PIT_ACCOUNT, MILITARY_ACCOUNT, ESV_ACCOUNT = "641", "642", "651"
TAX_PIT, TAX_MILITARY = "PIT", "MIL"
ACCRUAL_TYPES = (calc.SALARY, calc.PREMIUM, calc.SICK, calc.VACATION, calc.CIVIL)


class UAPayroll(AccountingDocument):
    """Нарахування зарплати за місяць.

    Salary, premium, vacation pay, sick pay (employer part): Dt 92/23/91/93 Ct 661.
    Sick pay, ФСС part: Dt 663 Ct 661. Civil-law contract: Dt 92 Ct 661.
    ПДФО: Dt 661 Ct 641 (PIT). Військовий збір: Dt 661 Ct 642 (MIL). ЄСВ of the employer: Dt 92/23/91/93 Ct 651.
    """

    doc_code = "PR"
    doc_title = "Нарахування зарплати"

    def validate(self):
        super().validate()
        self.check_period()
        if not self.lines:
            frappe.throw(_("Заповніть рядки нарахувань"))
        self.employees = {}
        for row in self.lines:
            self.check_line(row)
        self.check_salary_unique()
        for row in self.lines:
            self.calculate_gross(row)
        by_employee = {}
        for row in self.lines:
            by_employee.setdefault(row.employee, []).append(row)
        for name, rows in by_employee.items():
            calc.calculate_taxes(rows, self.employees[name], self.organization, self.month_start, self.name)
        self.set_totals()

    # ------------------------------------------------------------ checks

    def check_period(self):
        self.month_start = get_first_day(getdate(self.month_start))
        if not self.month_start <= getdate(self.posting_date) <= get_last_day(self.month_start):
            frappe.throw(_("Дата документа має бути в місяці нарахування"))

    def check_line(self, row):
        if row.employee not in self.employees:
            self.employees[row.employee] = calc.employee_info(row.employee)
        emp = self.employees[row.employee]
        if emp.organization != self.organization:
            frappe.throw(_("Рядок {0}: співробітник працює в іншій організації").format(row.idx))
        civil = emp.contract_type == calc.CONTRACT_CIVIL
        if row.accrual_type == calc.CIVIL and not civil:
            frappe.throw(_("Рядок {0}: «ЦПХ» нараховують за цивільно-правовим договором").format(row.idx))
        if row.accrual_type != calc.CIVIL and civil:
            frappe.throw(_("Рядок {0}: за цивільно-правовим договором нараховують лише «ЦПХ»").format(row.idx))
        if row.accrual_type in calc.PERIOD_TYPES:
            if not (row.period_from and row.period_to):
                frappe.throw(_("Рядок {0}: вкажіть період").format(row.idx))
            if getdate(row.period_to) < getdate(row.period_from):
                frappe.throw(_("Рядок {0}: кінець періоду раніше за початок").format(row.idx))
        if row.accrual_type in calc.INPUT_TYPES and flt(row.amount) <= 0:
            frappe.throw(_("Рядок {0}: сума має бути більше нуля").format(row.idx))
        row.expense_account = row.expense_account or DEFAULT_EXPENSE_ACCOUNT
        account = frappe.db.get_value("UA Account", row.expense_account, ["is_group", "off_balance"], as_dict=True)
        if not account or account.is_group or account.off_balance:
            frappe.throw(_("Рядок {0}: рахунок {1} не підходить для обліку").format(row.idx, row.expense_account))

    def check_salary_unique(self):
        """Salary of an employee is accrued once a month."""
        seen = {r.employee for r in self.lines if r.accrual_type == calc.SALARY}
        counts = [r.employee for r in self.lines if r.accrual_type == calc.SALARY]
        if len(counts) != len(seen):
            frappe.throw(_("Оклад співробітника нараховують один раз на місяць"))
        if not seen:
            return
        other = frappe.db.sql(
            """select p.name from `tabUA Payroll Line` l join `tabUA Payroll` p
            on p.name = l.parent and l.parenttype = 'UA Payroll'
            where p.docstatus = 1 and p.organization = %s and p.month_start = %s and p.name != %s
            and l.accrual_type = %s and l.employee in %s limit 1""",
            (self.organization, self.month_start, self.name or "", calc.SALARY, tuple(seen)),
        )
        if other:
            frappe.throw(_("За цей місяць оклад уже нараховано документом {0}").format(other[0][0]))

    # ------------------------------------------------------------ amounts

    def calculate_gross(self, row):
        emp = self.employees[row.employee]
        for field in ("worked_days", "norm_days", "avg_daily", "employer_part", "fss_part"):
            row.set(field, 0)
        if row.accrual_type == calc.SALARY:
            amount, worked, norm = calc.month_salary(emp, self.organization, self.month_start)
            row.amount, row.worked_days, row.norm_days = float(amount), float(worked), float(norm)
        elif row.accrual_type == calc.VACATION:
            average = calc.vacation_average(emp, self.organization, row.period_from)
            days = (getdate(row.period_to) - getdate(row.period_from)).days + 1
            row.avg_daily = float(average)
            row.amount = float(calc.q2(average * days))
        elif row.accrual_type == calc.SICK:
            average, amount, employer, fss = calc.sick_amounts(
                emp, self.organization, row.period_from, row.period_to, row.insured_years
            )
            row.avg_daily, row.amount = float(average), float(amount)
            row.employer_part, row.fss_part = float(employer), float(fss)
        else:
            row.amount = float(calc.q2(row.amount))

    def set_totals(self):
        def total(field):
            return flt(sum(flt(r.get(field)) for r in self.lines), 2)

        self.total_accrued = total("amount")
        self.total_pdfo = total("pdfo")
        self.total_military_levy = total("military_levy")
        self.total_esv = total("esv")
        self.total_net = total("net")

    # ------------------------------------------------------------ posting

    def build(self):
        entries = []
        # credit balance of the vacation reserve 471 that vacation lines may use (T-452)
        reserve = max(0.0, prov.credit_balance(self.organization, prov.VACATION_ACCOUNT, self.posting_date))
        for row in self.lines:
            person = self.employees[row.employee].person
            department = self.employees[row.employee].department
            cost = {"Department": department, "ExpenseItem": row.get("expense_item")}
            who = {"Person": person}
            if row.accrual_type == calc.SICK:
                entries.append(self.entry(row.expense_account, LIABILITY, row.employer_part, cost, who))
                entries.append(self.entry(FSS, LIABILITY, row.fss_part, who, who))
            elif row.accrual_type == calc.VACATION:
                # vacation pay and ЄСВ go against the reserve 471 first, only the excess to expense
                pay_reserve = flt(min(flt(row.amount), reserve), 2)
                reserve = flt(reserve - pay_reserve, 2)
                entries.append(self.entry(prov.VACATION_ACCOUNT, LIABILITY, pay_reserve, {}, who))
                entries.append(self.entry(row.expense_account, LIABILITY, flt(row.amount) - pay_reserve, cost, who))
            else:
                entries.append(self.entry(row.expense_account, LIABILITY, row.amount, cost, who))
            entries.append(self.entry(LIABILITY, PIT_ACCOUNT, row.pdfo, who, {"TaxType": TAX_PIT}))
            entries.append(self.entry(LIABILITY, MILITARY_ACCOUNT, row.military_levy, who, {"TaxType": TAX_MILITARY}))
            if row.accrual_type == calc.VACATION:
                esv_reserve = flt(min(flt(row.esv), reserve), 2)
                reserve = flt(reserve - esv_reserve, 2)
                entries.append(self.entry(prov.VACATION_ACCOUNT, ESV_ACCOUNT, esv_reserve, {}, {}))
                entries.append(self.entry(row.expense_account, ESV_ACCOUNT, flt(row.esv) - esv_reserve, cost, {}))
            else:
                entries.append(self.entry(row.expense_account, ESV_ACCOUNT, row.esv, cost, {}))
        return entries, [], []

    def before_cancel(self):
        super().before_cancel()
        payment = frappe.db.exists("UA Salary Payment", {"payroll": self.name, "docstatus": 1})
        if payment:
            frappe.throw(_("Спочатку скасуйте виплату зарплати {0}").format(payment))
