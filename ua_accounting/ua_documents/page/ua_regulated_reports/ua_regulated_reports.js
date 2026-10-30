frappe.pages["ua-regulated-reports"].on_page_load = function (wrapper) {
	wrapper.ua_report = new ua_accounting.reports.ReportPage(wrapper, ua_accounting.reports.CONFIG.regulated_reports);
};
