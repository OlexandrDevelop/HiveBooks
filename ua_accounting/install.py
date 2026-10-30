import frappe

from ua_accounting.setup import seed


def check_beeone():
    if not hasattr(frappe, "beeone_version"):
        raise RuntimeError(
            "ua_accounting requires beeone core (frappe.beeone_version). Pure upstream Frappe is not supported."
        )


def before_install():
    check_beeone()
    seed.create_roles()


REMINDER_METHOD = "ua_accounting.api.calendar.send_reminders"
REMINDER_JOB = "0 UA Accountant Task reminders"


def ensure_reminder_job():
    """The daily job of the accountant reminders, with a stable readable name (the list of jobs sorts by name)."""
    name = frappe.db.exists("Scheduled Job Type", {"method": REMINDER_METHOD, "frequency": "Daily"})
    if not name:
        name = frappe.get_doc(
            {"doctype": "Scheduled Job Type", "method": REMINDER_METHOD, "frequency": "Daily"}
        ).insert(ignore_permissions=True).name
    if name != REMINDER_JOB:
        frappe.rename_doc("Scheduled Job Type", name, REMINDER_JOB, force=True)


def ensure_nbu_job():
    """The daily job of the NBU rates; the exchange settings start and stop it."""
    from ua_accounting.ua_core.doctype.ua_exchange_settings.ua_exchange_settings import JOB_METHOD, sync_job

    if not frappe.db.exists("Scheduled Job Type", {"method": JOB_METHOD}):
        frappe.get_doc(
            {"doctype": "Scheduled Job Type", "method": JOB_METHOD, "frequency": "Daily"}
        ).insert(ignore_permissions=True)
        sync_job(frappe.db.get_single_value("UA Exchange Settings", "auto_load_rates") in (None, 1, "1"))


def ensure_ukrainian_language():
    """Make Ukrainian selectable in User Settings on every existing site."""
    if frappe.db.exists("Language", "uk"):
        frappe.db.set_value("Language", "uk", "enabled", 1, update_modified=False)


def after_install():
    seed.run()
    ensure_ukrainian_language()
    ensure_reminder_job()
    ensure_nbu_job()


def before_migrate():
    check_beeone()
    # roles must exist before doctypes and the workspace are synced
    seed.create_roles()


def after_migrate():
    seed.run()
    ensure_ukrainian_language()
    ensure_reminder_job()
    ensure_nbu_job()
