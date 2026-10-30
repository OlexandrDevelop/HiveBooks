"""Base classes of the documents of one fixed asset, intangible asset or low-value asset."""

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_first_day, get_last_day, getdate

from ua_accounting.accounting import assets
from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.accounting.utils import title_of


class AssetDocument(AccountingDocument):
    """Modernization, transfer, write-off, sale and revaluation: header with `asset_type` and `asset`."""

    def validate(self):
        super().validate()
        self.asset_type = self.asset_type or assets.FA
        self.acceptance = assets.require_accepted(self.asset_type, self.asset, self.organization)
        if getdate(self.posting_date) < getdate(self.acceptance.posting_date):
            frappe.throw(_("Дата документа раніше за дату прийняття активу до обліку"))
        disposal = assets.disposal_of(self.asset_type, self.asset, exclude=(self.doctype, self.name))
        if disposal:
            frappe.throw(_("Актив {0} уже вибув: {1}").format(self.asset_title, disposal[2]))

    @property
    def asset_title(self):
        return title_of(self.asset_type, self.asset)

    @property
    def asset_sub(self):
        return {assets.SUBCONTO[self.asset_type]: self.asset}

    @property
    def asset_account(self):
        return self.acceptance.asset_account

    @property
    def wear_account(self):
        return assets.WEAR_ACCOUNT[self.asset_type]

    def cost_and_wear(self):
        return assets.cost_at(self.acceptance, self.posting_date), assets.wear_at(self.acceptance, self.posting_date)

    def month_accrual(self):
        """Depreciation of the month of the disposal (it stops from the next month, НП(С)БО 7 п. 29).

        The monthly document skips the asset in this month, so the disposal accrues it itself.
        Nothing is accrued when the month is already depreciated, for low-value methods and for the
        production method: its output is known only to the monthly document, which must come first."""
        acc = self.acceptance
        if acc.depreciation_method in assets.LOW_VALUE_METHODS or acc.depreciation_method == assets.PRODUCTION:
            return 0.0
        if assets.depreciated_in_month(self.asset_type, self.asset, self.posting_date):
            return 0.0
        return assets.monthly_amounts(acc, get_last_day(getdate(self.posting_date)))[0]

    def disposal_cost_and_wear(self):
        """Cost and wear to write off: with the accrual of the month, or with the wear of the whole month
        if the month was depreciated by the monthly document."""
        acc = self.acceptance
        cost = assets.cost_at(acc, self.posting_date)
        if assets.depreciated_in_month(self.asset_type, self.asset, self.posting_date):
            return cost, assets.wear_at(acc, get_last_day(getdate(self.posting_date)))
        return cost, flt(assets.wear_at(acc, self.posting_date) + self.month_accrual(), 2)

    def residual_after_disposal(self):
        cost, wear = self.disposal_cost_and_wear()
        if self.asset_type == assets.LV and self.acceptance.depreciation_method in assets.LOW_VALUE_METHODS:
            return 0.0
        return flt(cost - wear, 2)

    def check_not_depreciated_later(self):
        if self.acceptance.depreciation_method == assets.PRODUCTION and not frappe.db.exists(
            assets.DEPRECIATION,
            {
                "organization": self.organization,
                "docstatus": 1,
                "posting_date": ("between", [get_first_day(self.posting_date), get_last_day(getdate(self.posting_date))]),
            },
        ):
            frappe.throw(
                _("Для активу {0} (виробничий метод) спочатку нарахуйте амортизацію за місяць вибуття з обсягом продукції").format(
                    self.asset_title
                )
            )
        if assets.depreciated_since(
            self.asset_type, self.asset, add_days(get_last_day(getdate(self.posting_date)), 1)
        ):
            frappe.throw(
                _("Для активу {0} проведено амортизацію не раніше {1}. Скасуйте її або вкажіть пізнішу дату").format(
                    self.asset_title, getdate(self.posting_date).strftime("%d.%m.%Y")
                )
            )

    def disposal_entries(self, residual_account):
        """Wear and residual cost go out of the asset account. A 50 % low-value asset first gets the other half."""
        acc = self.acceptance
        cost, wear = self.disposal_cost_and_wear()
        entries = []
        accrual = self.month_accrual()
        if accrual > 0:
            entries.append(
                self.entry(
                    assets.leaf_account(acc.expense_account or assets.DEFAULT_EXPENSE),
                    self.wear_account,
                    accrual,
                    {"Department": assets.department_of(acc, self.posting_date)},
                    self.asset_sub,
                )
            )
        if self.asset_type == assets.LV and acc.depreciation_method in assets.LOW_VALUE_METHODS:
            extra = flt(cost - wear, 2)
            if extra > 0:
                dept = assets.department_of(acc, self.posting_date)
                entries.append(
                    self.entry(
                        assets.leaf_account(acc.expense_account or assets.DEFAULT_EXPENSE),
                        self.wear_account,
                        extra,
                        {"Department": dept},
                        self.asset_sub,
                    )
                )
                wear = flt(wear + extra, 2)
        quantity = {"quantity_cr": 1}
        if wear > 0:
            entries.append(
                self.entry(self.wear_account, self.asset_account, wear, self.asset_sub, self.asset_sub, **quantity)
            )
            quantity = {}
        residual = flt(cost - wear, 2)
        if residual > 0:
            entries.append(self.entry(residual_account, self.asset_account, residual, {}, self.asset_sub, **quantity))
        return entries
