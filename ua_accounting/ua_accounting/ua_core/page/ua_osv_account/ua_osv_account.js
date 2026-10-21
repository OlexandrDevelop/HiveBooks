frappe.pages["ua-osv-account"].on_page_load = function (wrapper) {
	wrapper.ua_report = new ua_accounting.reports.ReportPage(wrapper, ua_accounting.reports.CONFIG.osv_account);
};
