import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import assets
from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.accounting.utils import title_of


class UAAssetAcceptance(AccountingDocument):
    """Прийняття до обліку ОЗ / НМА / МНМА.

    Fixed asset:      Dt 10x Ct 152
    Intangible asset: Dt 12x Ct 154
    Low-value asset:  Dt 112 Ct 153
    The depreciation parameters of the rows are used by the monthly depreciation.
    """

    doc_code = "OZ"
    doc_title = "Прийняття до обліку ОЗ / НМА"

    def validate(self):
        super().validate()
        if not self.assets:
            frappe.throw(_("Заповніть табличну частину «Активи»"))
        seen = set()
        for row in self.assets:
            self.check_row(row, seen)

    def check_row(self, row, seen):
        row.asset_type = row.asset_type or assets.FA
        if row.asset_type not in assets.ASSET_TYPES or not row.asset or not frappe.db.exists(row.asset_type, row.asset):
            frappe.throw(_("Рядок {0}: актив не знайдено").format(row.idx))
        title = title_of(row.asset_type, row.asset)
        card_org = assets.card_value(row.asset_type, row.asset, "organization")
        if card_org and card_org != self.organization:
            frappe.throw(_("Рядок {0}: актив {1} належить іншій організації").format(row.idx, title))
        if (row.asset_type, row.asset) in seen:
            frappe.throw(_("Рядок {0}: актив {1} вказано двічі").format(row.idx, title))
        seen.add((row.asset_type, row.asset))
        if flt(row.initial_cost) <= 0:
            frappe.throw(_("Рядок {0}: первісна вартість має бути більше нуля").format(row.idx))
        if flt(row.liquidation_value) < 0 or flt(row.liquidation_value) > flt(row.initial_cost):
            frappe.throw(_("Рядок {0}: ліквідаційна вартість має бути від 0 до первісної вартості").format(row.idx))

        row.depreciation_method = row.depreciation_method or assets.STRAIGHT
        allowed = assets.METHODS + (assets.LOW_VALUE_METHODS if row.asset_type == assets.LV else ())
        if row.depreciation_method not in allowed:
            frappe.throw(_("Рядок {0}: метод {1} не підходить для цього виду активу").format(row.idx, row.depreciation_method))
        if row.depreciation_method not in assets.LOW_VALUE_METHODS and (row.useful_life_months or 0) <= 0:
            frappe.throw(_("Рядок {0}: вкажіть строк корисного використання").format(row.idx))
        if row.depreciation_method == assets.PRODUCTION and flt(row.expected_output) <= 0:
            frappe.throw(_("Рядок {0}: вкажіть очікуваний обсяг продукції").format(row.idx))

        # place and person at the acceptance: the start of the history of transfers
        for field in ("department", "responsible"):
            if not row.get(field):
                row.set(field, assets.card_value(row.asset_type, row.asset, field))
        row.asset_account = row.asset_account or assets.default_account(row.asset_type, row.asset)
        assets.check_asset_account(row.asset_type, row.asset_account)
        row.expense_account = row.expense_account or assets.DEFAULT_EXPENSE
        assets.check_expense_account(row.expense_account)

    def before_submit(self):
        for row in self.assets:
            other = assets.acceptance_of(row.asset_type, row.asset, exclude=self.name)
            if other:
                frappe.throw(
                    _("Актив {0} уже прийнято до обліку документом {1}").format(
                        title_of(row.asset_type, row.asset), other.document
                    )
                )

    def build(self):
        entries = []
        for row in self.assets:
            sub = {assets.SUBCONTO[row.asset_type]: row.asset}
            entries.append(
                self.entry(
                    row.asset_account, assets.PURCHASE_ACCOUNT[row.asset_type], row.initial_cost, sub, sub, quantity_dr=1
                )
            )
        return entries, [], []

    def on_submit(self):
        super().on_submit()
        for row in self.assets:
            values = {
                "commissioning_date": self.posting_date,
                "useful_life_months": row.useful_life_months,
                "depreciation_method": row.depreciation_method,
            }
            meta = frappe.get_meta(row.asset_type)
            values = {k: v for k, v in values.items() if meta.has_field(k)}
            if not meta.get("organization") or not frappe.db.get_value(row.asset_type, row.asset, "organization"):
                values["organization"] = self.organization
            frappe.db.set_value(row.asset_type, row.asset, values, update_modified=False)

    def before_cancel(self):
        super().before_cancel()
        for row in self.assets:
            if assets.has_dependents(row.asset_type, row.asset):
                frappe.throw(
                    _("Для активу {0} є документи після прийняття до обліку. Спочатку скасуйте їх").format(
                        title_of(row.asset_type, row.asset)
                    )
                )

    def on_cancel(self):
        super().on_cancel()
        for row in self.assets:
            if frappe.get_meta(row.asset_type).has_field("commissioning_date"):
                frappe.db.set_value(row.asset_type, row.asset, "commissioning_date", None, update_modified=False)
