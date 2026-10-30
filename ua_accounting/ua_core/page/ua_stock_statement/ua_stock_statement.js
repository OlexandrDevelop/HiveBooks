frappe.pages["ua-stock-statement"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: "Відомість по товарах на складах", single_column: true});
	const $body = $(wrapper).find(".layout-main-section");
	$body.html(`<div class="ua-card"><h2>Відомість по товарах на складах</h2><p>Залишки та оберти товарів за період.</p>
		<button class="btn btn-primary">Відкрити звіт</button></div>`);
	$body.find("button").on("click", () => frappe.set_route("query-report", "UA Stock Statement"));
};
