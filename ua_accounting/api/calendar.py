import frappe

from ua_accounting.accounting import accountant_tasks as tasks
from ua_accounting.api.helpers import check_access


@frappe.whitelist(methods=["POST"])
def generate(organization, year):
    """Create the tasks of the taxes and reports of a year. Existing tasks are kept."""
    check_access(organization)
    frappe.has_permission(tasks.TASK, "create", throw=True)
    return tasks.generate(organization, year)


@frappe.whitelist(methods=["GET", "POST"])
def get_home(organization, today=None, horizon_days=30):
    """Overdue, today's and upcoming tasks for the home page."""
    check_access(organization)
    return tasks.get_home(organization, today, horizon_days)


@frappe.whitelist(methods=["POST"])
def complete(name):
    check_access(None)
    return tasks.complete(name)


@frappe.whitelist(methods=["POST"])
def reopen(name):
    check_access(None)
    return tasks.reopen(name)


@frappe.whitelist(methods=["POST"])
def send_reminders(today=None):
    """One notification per task, user and day for tasks that are near the deadline. Runs daily."""
    check_access(None)
    return tasks.send_reminders(today)
