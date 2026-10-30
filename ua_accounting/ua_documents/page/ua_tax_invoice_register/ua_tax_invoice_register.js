frappe.pages["ua-tax-invoice-register"].on_page_load = function (wrapper) {
	wrapper.ua_report = new ua_accounting.reports.ReportPage(wrapper, ua_accounting.reports.CONFIG.tax_invoice_register);
};
