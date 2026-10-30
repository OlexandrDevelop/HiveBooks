import frappe

from ua_accounting.accounting import provisions as prov
from ua_accounting.accounting.utils import title_of


def check_access():
    frappe.has_permission("UA Provision Accrual", "read", throw=True)


@frappe.whitelist(methods=["GET", "POST"])
def calculate_doubtful(organization, date, method=None):
    """Reserve of doubtful debts per settlement document at `date`."""
    check_access()
    result = prov.calculate_doubtful(organization, date, method)
    for row in result["rows"]:
        row["counterparty_title"] = title_of("UA Counterparty", row["counterparty"])
        row["contract_title"] = title_of("UA Counterparty Contract", row["contract"])
    return result


@frappe.whitelist(methods=["GET", "POST"])
def calculate_vacation(organization, period):
    """Coefficient, base and amount of the vacation reserve of a month."""
    check_access()
    result = prov.calculate_vacation(organization, period)
    return {"coefficient": result["coefficient"], "base": result["base"], "amount": result["amount"]}


@frappe.whitelist(methods=["GET", "POST"])
def vacation_pay_split(organization, date, amount):
    check_access()
    covered, rest = prov.split(organization, prov.VACATION_ACCOUNT, date, amount)
    return {"from_reserve": covered, "to_expense": rest}


@frappe.whitelist(methods=["GET", "POST"])
def calculate_warranty(organization, period):
    check_access()
    return prov.calculate_warranty(organization, period)


@frappe.whitelist(methods=["GET", "POST"])
def warranty_split(organization, date, amount):
    check_access()
    covered, rest = prov.split(organization, prov.WARRANTY_ACCOUNT, date, amount)
    return {"from_provision": covered, "to_expense": rest}
