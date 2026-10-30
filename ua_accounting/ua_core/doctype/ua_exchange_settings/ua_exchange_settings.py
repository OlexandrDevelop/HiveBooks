import frappe
from frappe import _
from frappe.model.document import Document

JOB_METHOD = "ua_accounting.exchange.nbu.scheduled_load"


class UAExchangeSettings(Document):
    def validate(self):
        for field in ("nbu_rates_url", "nbu_banks_url"):
            url = (self.get(field) or "").strip()
            if url:
                from ua_accounting.exchange.nbu import check_url

                check_url(url)
        if self.nbu_rates_url and "{date}" not in self.nbu_rates_url:
            frappe.throw(_("В адресі курсів потрібне місце для дати: {date}"))

    def on_update(self):
        sync_job(self.auto_load_rates)


def sync_job(enabled):
    """The daily job loads rates only when the setting is on."""
    for name in frappe.get_all("Scheduled Job Type", filters={"method": JOB_METHOD}, pluck="name"):
        frappe.db.set_value("Scheduled Job Type", name, "stopped", 0 if enabled else 1)
    # the framework runs the rates by the schedule of its rule
    if frappe.db.exists("Exchange Rule", "NBU rates"):
        frappe.db.set_value("Exchange Rule", "NBU rates", "schedule", "Daily" if enabled else "Manual")
