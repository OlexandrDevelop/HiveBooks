frappe.pages["ua-stock-balance"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: "Залишки товарів", single_column: true});
	const $body = $(wrapper).find(".layout-main-section");
	$body.html(`<div class="ua-card"><h2>Залишки товарів</h2><p>Кількість і вартість товарів на складах на дату.</p>
		<button class="btn btn-primary">Відкрити звіт</button></div>`);
	$body.find("button").on("click", () => frappe.set_route("query-report", "UA Stock Balance"));
};
