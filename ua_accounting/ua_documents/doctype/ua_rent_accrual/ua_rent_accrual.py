import calendar

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate

from ua_accounting.accounting import leases
from ua_accounting.accounting.documents import EVENT_SHIPMENT, EXPENSE_ACCOUNT, TAX_VAT, vat_info

SETTLEMENT_ACCOUNT = "631"
VAT_CREDIT_ACCOUNT = "644"
VAT_ACCOUNT = "641"


class UARentAccrual(leases.LeaseDocument):
    """Нарахування орендної плати (операційна оренда).

    Dt 92 Kt 631   rent without VAT, by the days of the month the object was at the lessee
    Dt 644 Kt 631  VAT in the debt to the lessor
    Dt 641 Kt 644  VAT credit, if the tax invoice is received
    """

    doc_code = "RNT"
    doc_title = "Нарахування орендної плати"
    kind = leases.OPERATING

    def validate(self):
        super().validate()
        last = calendar.monthrange(getdate(self.posting_date).year, getdate(self.posting_date).month)[1]
        if getdate(self.posting_date).day != last:
            frappe.throw(_("Оренда нараховується на кінець місяця"))
        if not self.leases:
            frappe.throw(_("Додайте договори оренди"))
        seen = set()
        for line in self.leases:
            if line.lease in seen:
                frappe.throw(_("Рядок {0}: договір {1} вже є в документі").format(line.idx, line.lease))
            seen.add(line.lease)
            self.calculate_line(line)

    def calculate_line(self, line):
        lease = frappe.get_doc(leases.LEASE, line.lease)
        if lease.organization != self.organization or lease.lease_kind != self.kind:
            frappe.throw(_("Рядок {0}: договір {1} не підходить до документа").format(line.idx, line.lease))
        line.counterparty = lease.counterparty
        days, month_days = leases.rent_days(line.lease, self.posting_date, lease.end_date)
        line.days = days
        if not days:
            frappe.throw(_("Рядок {0}: за договором {1} у цьому місяці майна в оренді немає").format(line.idx, line.lease))
        month = get_first_day(self.posting_date)
        if self.same_month_accrual(line.lease, month):
            frappe.throw(_("Рядок {0}: оренду за договором {1} за цей місяць вже нараховано").format(line.idx, line.lease))
        gross = flt(flt(lease.monthly_rent) * days / month_days, 2)
        percent, taxable = vat_info(lease.vat_rate, {})
        if taxable and percent:
            line.amount_net = flt(gross / (1 + percent / 100), 2)
            line.vat_amount = flt(gross - line.amount_net, 2)
        else:
            line.amount_net, line.vat_amount = gross, 0

    def same_month_accrual(self, lease, month):
        rows = frappe.db.sql(
            """select p.name from `tabUA Rent Accrual` p join `tabUA Rent Accrual Line` l on l.parent = p.name
            where l.lease = %s and p.docstatus < 2 and p.name != %s and p.posting_date between %s and %s limit 1""",
            (lease, self.name or "", month, get_last_day(month)),
        )
        return bool(rows)

    def build(self):
        entries, credits = [], []
        for line in self.leases:
            lease = frappe.get_doc(leases.LEASE, line.lease)
            sub = self.settle_sub(lease)
            entries.append(
                self.entry(EXPENSE_ACCOUNT, SETTLEMENT_ACCOUNT, line.amount_net, {}, sub)
            )
            if flt(line.vat_amount):
                entries.append(
                    self.entry(VAT_CREDIT_ACCOUNT, SETTLEMENT_ACCOUNT, line.vat_amount, {"TaxType": TAX_VAT}, sub)
                )
                if line.tax_invoice:
                    entries.append(
                        self.entry(VAT_ACCOUNT, VAT_CREDIT_ACCOUNT, line.vat_amount, {"TaxType": TAX_VAT}, {"TaxType": TAX_VAT})
                    )
                    credits.append(
                        self.vat_row(
                            lease.vat_rate, line.amount_net, line.vat_amount, EVENT_SHIPMENT,
                            counterparty=lease.counterparty, contract=lease.contract,
                        )
                    )
        return entries, [], credits
