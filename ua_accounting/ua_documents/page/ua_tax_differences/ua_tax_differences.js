frappe.pages["ua-tax-differences"].on_page_load = function (wrapper) {
	wrapper.ua_report = new ua_accounting.reports.ReportPage(wrapper, ua_accounting.reports.CONFIG.tax_differences);
};
