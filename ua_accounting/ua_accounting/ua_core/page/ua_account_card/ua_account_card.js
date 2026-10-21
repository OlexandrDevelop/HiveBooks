frappe.pages["ua-account-card"].on_page_load = function (wrapper) {
	wrapper.ua_report = new ua_accounting.reports.ReportPage(wrapper, ua_accounting.reports.CONFIG.account_card);
};
