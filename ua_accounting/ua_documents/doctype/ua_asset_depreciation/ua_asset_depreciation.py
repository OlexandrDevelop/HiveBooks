import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate

from ua_accounting.accounting import assets, ledger
from ua_accounting.accounting.documents import AccountingDocument


class UAAssetDepreciation(AccountingDocument):
    """Нарахування амортизації за місяць (дата документа — останній день місяця).

    Dt 23 / 91x / 92 / 93 / 94x (by the acceptance row)  Ct 131 / 132 / 133
    The table of the amounts is filled by the program from the acceptances, modernizations and the output.
    """

    doc_code = "AM"
    doc_title = "Нарахування амортизації"

    def validate(self):
        super().validate()
        date = getdate(self.posting_date)
        if date != get_last_day(date):
            frappe.throw(_("Дата нарахування амортизації — останній день місяця"))
        same = frappe.db.exists(
            self.doctype,
            {
                "organization": self.organization,
                "docstatus": 1,
                "posting_date": ("between", [get_first_day(date), date]),
                "name": ("!=", self.name or ""),
            },
        )
        if same:
            frappe.throw(_("За цей місяць амортизацію вже нараховано: {0}").format(same))
        output = {}
        for row in self.output or []:
            row.asset_type = row.asset_type or assets.FA
            if flt(row.quantity) < 0:
                frappe.throw(_("Рядок {0}: обсяг продукції не може бути від'ємним").format(row.idx))
            key = (row.asset_type, row.asset)
            output[key] = flt(output.get(key, 0) + flt(row.quantity), 3)
        self.set("assets", [])
        for row in assets.depreciation_rows(self.organization, date, output):
            self.append("assets", row)
        self.total_amount = flt(sum(flt(r.amount) for r in self.assets), 2)

    def before_cancel(self):
        super().before_cancel()
        later = frappe.db.exists(
            self.doctype,
            {"organization": self.organization, "docstatus": 1, "posting_date": (">", self.posting_date)},
        )
        if later:
            frappe.throw(_("Спочатку скасуйте амортизацію за пізніші місяці: {0}").format(later))
        self.check_no_disposal_in_month()

    def check_no_disposal_in_month(self):
        for row in self.assets:
            if assets.disposal_of(row.asset_type, row.asset):
                disposed = assets.disposal_of(row.asset_type, row.asset)
                if get_first_day(self.posting_date) <= disposed[0] <= getdate(self.posting_date):
                    frappe.throw(_("Актив {0} вибув у цьому місяці: {1}. Спочатку скасуйте цей документ").format(
                        row.asset, disposed[2]))

    def post_document(self):
        # a month without any amount is allowed: nothing to post
        self._ctx = {}
        entries = self.build()[0]
        if entries:
            ledger.post_entries(self, entries)

    def build(self):
        entries = []
        for row in self.assets:
            if flt(row.amount) <= 0:
                continue
            entries.append(
                self.entry(
                    assets.leaf_account(row.expense_account or assets.DEFAULT_EXPENSE),
                    assets.WEAR_ACCOUNT[row.asset_type],
                    row.amount,
                    {"Department": row.department},
                    {assets.SUBCONTO[row.asset_type]: row.asset},
                )
            )
        return entries, [], []
