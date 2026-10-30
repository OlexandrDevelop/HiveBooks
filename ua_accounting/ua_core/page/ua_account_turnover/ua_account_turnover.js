frappe.pages["ua-account-turnover"].on_page_load = function (wrapper) {
	ua_accounting.reports.open_more(wrapper, "account_turnover");
};
