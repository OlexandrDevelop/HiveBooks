import frappe

from ua_accounting.accounting import month_closing


@frappe.whitelist(methods=["POST"])
def open_closing(organization, period):
    """The closing of the month (created when missing) with the status of every step."""
    return month_closing.open_closing(organization, period)


@frappe.whitelist(methods=["POST"])
def run_step(name, step):
    """Run one step. A done step is re-run: the later steps are cancelled first."""
    return month_closing.run_step(name, step)


@frappe.whitelist(methods=["POST"])
def run_all(name):
    """Run all steps in order, stop at the first error."""
    return month_closing.run_all(name)


@frappe.whitelist(methods=["POST"])
def cancel_step(name, step):
    """Cancel one step. Refused while a later step is done."""
    return month_closing.cancel_step(name, step)


@frappe.whitelist(methods=["POST"])
def cancel_all(name):
    """Cancel all done steps from the last to the first."""
    return month_closing.cancel_all(name)
