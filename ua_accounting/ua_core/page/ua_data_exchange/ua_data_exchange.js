// Data exchange: import from 1C and Excel, bank statements, NBU rates, classifiers, files for M.E.Doc and Вчасно.
frappe.pages["ua-data-exchange"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Обмін даними"),
		single_column: true,
	});
	const API = "ua_accounting.api.exchange.";
	const esc = frappe.utils.escape_html;
	const KIND = {
		catalogs_1c: "Довідники з 1С",
		balances_1c: "Залишки з 1С",
		catalogs_excel: "Довідники з Excel",
		balances_excel: "Залишки з Excel",
		bank_statement: "Банківська виписка",
		payment_orders: "Платіжні доручення",
		nbu_rates: "Курси НБУ",
		banks: "Довідник банків",
		classifier: "Класифікатор",
		tax_invoices: "Податкові накладні",
	};
	const $bar = $('<div class="ua-exchange-bar" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px"></div>').appendTo(page.main);
	const $log = $('<div class="ua-exchange-log"></div>').appendTo(page.main);

	const FILE_FIELD = (name) => ({
		fieldtype: "HTML",
		fieldname: name,
		options: `<div class="form-group"><label class="control-label">${__("Файл")}</label>
			<input type="file" class="form-control ua-exchange-file" style="height:auto"></div>`,
	});

	function pick_file(dialog) {
		const file = dialog.$wrapper.find(".ua-exchange-file")[0].files[0];
		if (!file) {
			frappe.throw(__("Оберіть файл"));
		}
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve({ name: file.name, content: String(reader.result).split(",")[1] || "" });
			reader.onerror = () => reject(new Error(__("Не вдалося прочитати файл")));
			reader.readAsDataURL(file);
		});
	}

	function call(method, args, freeze_message) {
		return frappe.call({ method: API + method, args, freeze: true, freeze_message: freeze_message || __("Зачекайте...") });
	}

	function counts(obj) {
		const parts = Object.entries(obj || {}).map(([k, v]) => `${esc(__(k))}: ${v}`);
		return parts.length ? parts.join(", ") : "—";
	}

	function show_result(title, res) {
		let html = `<p>${__("Створено")}: ${counts(res.created)}</p><p>${__("Оновлено")}: ${counts(res.updated)}</p>`;
		const errors = res.errors || [];
		if (errors.length) {
			html += `<p><b>${__("Помилки")} (${errors.length}):</b></p><ul>${errors
				.slice(0, 50)
				.map((e) => `<li>${e.row ? __("Рядок") + " " + e.row + ": " : ""}${esc(e.message || e)}</li>`)
				.join("")}</ul>`;
		}
		frappe.msgprint({ title, message: html, indicator: errors.length ? "orange" : "green" });
		refresh_log();
	}

	function download(filename, base64, mime) {
		const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
		const url = URL.createObjectURL(new Blob([bytes], { type: mime || "application/octet-stream" }));
		const a = document.createElement("a");
		a.href = url;
		a.download = filename;
		document.body.appendChild(a);
		a.click();
		a.remove();
		setTimeout(() => URL.revokeObjectURL(url), 2000);
	}

	// ------------------------------------------------------------------ import from 1C and Excel
	function import_1c() {
		const dialog = new frappe.ui.Dialog({
			title: __("Імпорт з 1С"),
			fields: [
				{ fieldtype: "Link", fieldname: "organization", label: __("Організація"), options: "UA Organization", reqd: 1 },
				{
					fieldtype: "Select",
					fieldname: "source",
					label: __("Джерело"),
					options: [
						{ label: __("1С Бухгалтерія для України (XML)"), value: "xml" },
						{ label: __("Шаблон Excel"), value: "excel" },
					],
					default: "xml",
				},
				{
					fieldtype: "Select",
					fieldname: "kind",
					label: __("Що завантажувати"),
					options: [
						{ label: __("Довідники"), value: "catalogs" },
						{ label: __("Залишки"), value: "balances" },
						{ label: __("Контрагенти"), value: "counterparties" },
						{ label: __("Номенклатура"), value: "items" },
						{ label: __("Склади"), value: "warehouses" },
					],
					default: "catalogs",
				},
				FILE_FIELD("file_html"),
				{ fieldtype: "Date", fieldname: "date", label: __("Дата залишків"), description: __("Якщо порожньо — з файлу") },
				{ fieldtype: "Check", fieldname: "replace", label: __("Замінити раніше введені залишки") },
				{ fieldtype: "Check", fieldname: "dry_run", label: __("Тільки перевірити") },
				{ fieldtype: "Button", fieldname: "template", label: __("Завантажити шаблон Excel") },
			],
			primary_action_label: __("Імпортувати"),
			primary_action: async (v) => {
				const file = await pick_file(dialog);
				const excel = v.source === "excel";
				const kind = v.kind;
				const xml_ok = ["catalogs", "balances"].includes(kind);
				const excel_ok = ["counterparties", "items", "warehouses", "balances"].includes(kind);
				if ((excel && !excel_ok) || (!excel && !xml_ok)) {
					frappe.throw(excel ? __("Для Excel оберіть контрагентів, номенклатуру, склади або залишки") : __("Для 1С оберіть довідники або залишки"));
				}
				const r = await call(excel ? "import_excel" : "import_1c_xml", {
					organization: v.organization,
					kind,
					content: file.content,
					file_name: file.name,
					date: v.date || undefined,
					replace: v.replace ? 1 : 0,
					dry_run: v.dry_run ? 1 : 0,
				});
				dialog.hide();
				show_result(v.dry_run ? __("Перевірка файлу") : __("Імпорт завершено"), r.message);
			},
		});
		dialog.fields_dict.template.input.onclick = async () => {
			const kind = dialog.get_value("kind");
			if (dialog.get_value("source") !== "excel" || kind === "catalogs") {
				frappe.msgprint(__("Оберіть шаблон Excel і вид даних"));
				return;
			}
			const r = await call("get_template", { kind });
			download(r.message.filename, r.message.content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
		};
		dialog.show();
	}

	// ------------------------------------------------------------------ bank statement
	function import_statement() {
		const dialog = new frappe.ui.Dialog({
			title: __("Імпорт виписки"),
			fields: [
				{ fieldtype: "Link", fieldname: "bank_account", label: __("Банківський рахунок"), options: "UA Bank Account", reqd: 1 },
				{
					fieldtype: "Select",
					fieldname: "format",
					label: __("Формат"),
					options: [
						{ label: __("Визначити автоматично"), value: "auto" },
						{ label: "iBank2", value: "ibank2" },
						{ label: "Приват24", value: "privat24" },
						{ label: "Ощадбанк (MT940)", value: "oschad" },
					],
					default: "auto",
				},
				FILE_FIELD("file_html"),
				{ fieldtype: "Check", fieldname: "post", label: __("Одразу створити документи за розпізнаними рядками") },
			],
			primary_action_label: __("Імпортувати"),
			primary_action: async (v) => {
				const file = await pick_file(dialog);
				const r = await call("import_bank_statement", {
					bank_account: v.bank_account, format: v.format, content: file.content, file_name: file.name,
				});
				const res = r.message;
				let posted = "";
				if (v.post && res.statement) {
					const p = await call("post_statement", { name: res.statement });
					posted = `<p>${__("Створено документів")}: ${p.message.posted}, ${__("пропущено")}: ${p.message.skipped}</p>`;
				}
				dialog.hide();
				const warn = (res.warnings || []).map((w) => `<li>${esc(w)}</li>`).join("");
				frappe.msgprint({
					title: __("Виписку завантажено"),
					indicator: res.balance_ok === false ? "orange" : "green",
					message: `<p>${__("Рядків у файлі")}: ${res.lines}, ${__("нових")}: ${res.new}, ${__("повторів")}: ${res.duplicates}</p>
						<p>${__("Розпізнано")}: ${res.matched}, ${__("не розпізнано")}: ${res.unmatched}</p>${posted}
						${warn ? "<ul>" + warn + "</ul>" : ""}`,
				});
				refresh_log();
			},
		});
		dialog.show();
	}

	// ------------------------------------------------------------------ payment orders
	async function export_orders() {
		const rows = await frappe.db.get_list("UA Payment Order", {
			filters: { docstatus: 1, status: ["!=", "Сплачено"] },
			fields: ["name", "number", "posting_date", "recipient_name", "amount", "organization"],
			order_by: "posting_date desc",
			limit: 100,
		});
		const dialog = new frappe.ui.Dialog({
			title: __("Експорт платіжних доручень"),
			fields: [
				{
					fieldtype: "Select",
					fieldname: "format",
					label: __("Формат"),
					options: [
						{ label: "iBank2", value: "ibank2" },
						{ label: "Приват24", value: "privat24" },
						{ label: "Ощадбанк", value: "oschad" },
					],
					default: "ibank2",
				},
				{
					fieldtype: "MultiCheck",
					fieldname: "orders",
					label: __("Платіжні доручення"),
					columns: 1,
					options: rows.map((r) => ({
						label: `№${r.number || r.name} ${frappe.datetime.str_to_user(r.posting_date)} ${r.recipient_name || ""} ${format_currency(r.amount)}`,
						value: r.name,
					})),
				},
			],
			primary_action_label: __("Вивантажити"),
			primary_action: async (v) => {
				const names = dialog.fields_dict.orders.get_checked_options();
				if (!names.length) frappe.throw(__("Оберіть платіжні доручення"));
				const r = await call("export_payment_orders", { names, format: v.format });
				const res = r.message;
				const mime = res.encoding === "utf-8" ? "text/csv" : "text/plain";
				download(res.filename, res.content, mime);
				dialog.hide();
				frappe.show_alert({ message: __("Вивантажено доручень: {0}", [res.count]), indicator: "green" });
				refresh_log();
			},
		});
		dialog.show();
	}

	// ------------------------------------------------------------------ NBU
	function load_rates() {
		const today = frappe.datetime.get_today();
		const dialog = new frappe.ui.Dialog({
			title: __("Завантажити курси НБУ"),
			fields: [
				{ fieldtype: "Date", fieldname: "date_from", label: __("З дати"), default: today },
				{ fieldtype: "Date", fieldname: "date_to", label: __("По дату"), default: today },
			],
			primary_action_label: __("Завантажити"),
			primary_action: async (v) => {
				const r = await call("load_nbu_rates", { date_from: v.date_from, date_to: v.date_to }, __("Завантаження курсів НБУ..."));
				dialog.hide();
				const res = r.message;
				const loaded = Object.entries(res.loaded).map(([k, rate]) => `${esc(k)}: ${rate}`).join(", ") || "—";
				frappe.msgprint({
					title: __("Курси НБУ"),
					indicator: res.errors.length ? "orange" : "green",
					message: `<p>${__("Днів")}: ${res.days}. ${__("Курси")}: ${loaded}</p>${res.errors.map((e) => `<p>${esc(e)}</p>`).join("")}`,
				});
				refresh_log();
			},
		});
		dialog.show();
	}

	async function load_banks() {
		const r = await call("load_banks", {}, __("Оновлення довідника банків..."));
		const res = r.message;
		frappe.msgprint({
			title: __("Довідник банків"),
			indicator: res.errors.length ? "orange" : "green",
			message: `<p>${__("Створено")}: ${res.created}, ${__("оновлено")}: ${res.updated}, ${__("закрито")}: ${res.deactivated}</p>${(res.errors || [])
				.map((e) => `<p>${esc(e.message || e)}</p>`)
				.join("")}`,
		});
		refresh_log();
	}

	// ------------------------------------------------------------------ classifiers
	function classifiers() {
		const dialog = new frappe.ui.Dialog({
			title: __("Класифікатори"),
			fields: [
				{
					fieldtype: "Select",
					fieldname: "kind",
					label: __("Класифікатор"),
					options: [
						{ label: "УКТЗЕД", value: "uktzed" },
						{ label: "КВЕД", value: "kved" },
						{ label: "ДКПП", value: "dkpp" },
					],
					default: "uktzed",
				},
				FILE_FIELD("file_html"),
				{ fieldtype: "HTML", fieldname: "hint", options: `<p class="text-muted">${__("Файл CSV у кодуванні UTF-8: код;назва")}</p>` },
			],
			primary_action_label: __("Завантажити"),
			primary_action: async (v) => {
				const file = await pick_file(dialog);
				const r = await call("load_classifier", { kind: v.kind, content: file.content });
				dialog.hide();
				show_result(__("Класифікатор завантажено"), {
					created: { [__("Записів")]: r.message.created },
					updated: { [__("Записів")]: r.message.updated },
					errors: r.message.errors,
				});
			},
		});
		dialog.show();
	}

	// ------------------------------------------------------------------ M.E.Doc and Вчасно
	function export_tax(target, title) {
		const dialog = new frappe.ui.Dialog({
			title,
			fields: [
				{ fieldtype: "Link", fieldname: "organization", label: __("Організація"), options: "UA Organization", reqd: 1 },
				{ fieldtype: "Date", fieldname: "date_from", label: __("З дати"), default: frappe.datetime.month_start() },
				{ fieldtype: "Date", fieldname: "date_to", label: __("По дату"), default: frappe.datetime.get_today() },
				{ fieldtype: "Button", fieldname: "find", label: __("Показати документи") },
				{ fieldtype: "MultiCheck", fieldname: "docs", label: __("Документи"), columns: 1, options: [] },
			],
			primary_action_label: __("Вивантажити"),
			primary_action: async () => {
				const picked = dialog.fields_dict.docs.get_checked_options();
				if (!picked.length) frappe.throw(__("Оберіть документи"));
				const items = picked.map((p) => JSON.parse(p));
				const r = await call("export_tax_invoices", { items, target });
				r.message.files.forEach((f, i) => {
					setTimeout(() => download(f.filename, f.content, f.filename.endsWith(".csv") ? "text/csv" : "application/xml"), i * 400);
				});
				dialog.hide();
				frappe.show_alert({ message: __("Вивантажено документів: {0}", [r.message.count]), indicator: "green" });
				refresh_log();
			},
		});
		dialog.fields_dict.find.input.onclick = async () => {
			const v = dialog.get_values(true);
			if (!v.organization) return frappe.msgprint(__("Вкажіть організацію"));
			const filters = { docstatus: 1, organization: v.organization, posting_date: ["between", [v.date_from, v.date_to]] };
			const fields = ["name", "number", "posting_date", "counterparty"];
			const [pn, rk] = await Promise.all([
				frappe.db.get_list("UA Tax Invoice", { filters, fields, limit: 200 }),
				frappe.db.get_list("UA Tax Adjustment", { filters, fields, limit: 200 }),
			]);
			const options = [
				...pn.map((d) => ({ doctype: "UA Tax Invoice", ...d, prefix: __("ПН") })),
				...rk.map((d) => ({ doctype: "UA Tax Adjustment", ...d, prefix: __("РК") })),
			].map((d) => ({
				label: `${d.prefix} №${d.number || ""} ${frappe.datetime.str_to_user(d.posting_date)}`,
				value: JSON.stringify({ doctype: d.doctype, name: d.name }),
			}));
			const field = dialog.fields_dict.docs;
			field.df.options = options;
			field.refresh();
		};
		dialog.show();
	}

	// ------------------------------------------------------------------ log
	function refresh_log() {
		frappe.db
			.get_list("UA Exchange Log", {
				fields: ["name", "timestamp", "direction", "kind", "file_name", "status", "created", "updated", "errors", "user"],
				order_by: "creation desc",
				limit: 50,
			})
			.then((rows) => {
				const body = rows
					.map(
						(r) => `<tr>
						<td>${esc(frappe.datetime.str_to_user(r.timestamp || ""))}</td>
						<td>${esc(r.direction)}</td>
						<td>${esc(__(KIND[r.kind] || r.kind))}</td>
						<td>${esc(r.file_name || "")}</td>
						<td>${esc(r.status)}</td>
						<td class="text-right">${r.created || 0}</td>
						<td class="text-right">${r.updated || 0}</td>
						<td class="text-right">${r.errors || 0}</td>
						<td>${esc(r.user || "")}</td></tr>`
					)
					.join("");
				$log.html(`<h5>${__("Журнал обміну")}</h5>
					<table class="table table-bordered ua-num"><thead><tr>
					<th>${__("Час")}</th><th>${__("Напрям")}</th><th>${__("Вид обміну")}</th><th>${__("Файл")}</th><th>${__("Стан")}</th>
					<th class="text-right">${__("Створено")}</th><th class="text-right">${__("Оновлено")}</th>
					<th class="text-right">${__("Помилок")}</th><th>${__("Користувач")}</th></tr></thead>
					<tbody>${body || `<tr><td colspan="9" class="text-muted">${__("Записів ще немає")}</td></tr>`}</tbody></table>`);
			});
	}

	[
		[__("Імпорт з 1С"), import_1c],
		[__("Імпорт виписки"), import_statement],
		[__("Експорт платіжних доручень"), export_orders],
		[__("Завантажити курси НБУ"), load_rates],
		[__("Оновити довідник банків"), load_banks],
		[__("Класифікатори"), classifiers],
		[__("Експорт ПН для M.E.Doc"), () => export_tax("medoc", __("Експорт ПН для M.E.Doc"))],
		[__("Експорт ПН для Вчасно"), () => export_tax("vchasno", __("Експорт ПН для Вчасно"))],
	].forEach(([label, action]) => {
		$(`<button class="btn btn-default btn-sm">${esc(label)}</button>`).appendTo($bar).on("click", action);
	});
	refresh_log();
};
