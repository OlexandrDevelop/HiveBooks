// Home page "Головне" (design/mockups/home.html): quick create, balance cards from the ledger,
// recent documents, favourites and reminders. Data: ua_home.py (read only).
frappe.pages["ua-home"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: __("Головне"), single_column: true });
	$(wrapper).find(".layout-main-section").append('<div class="ua-home"></div>');
	$(document).on("ua-org-changed ua-favs-changed", () => {
		if ($(wrapper).is(":visible")) frappe.pages["ua-home"].on_page_show(wrapper);
	});
};

frappe.pages["ua-home"].on_page_show = function (wrapper) {
	const ui = ua_accounting.ui;
	const shell = ua_accounting.shell;
	const esc = ui.esc;
	const icon = ui.icon;
	const METHOD = "ua_accounting.ua_core.page.ua_home.ua_home.";
	const $root = $(wrapper).find(".ua-home");
	const org = shell.current_org ? shell.current_org() : null;
	const state = wrapper.ua_home || (wrapper.ua_home = { mode: "all" });

	const hour = new Date().getHours();
	const hello =
		hour < 5 ? __("Доброї ночі") : hour < 12 ? __("Доброго ранку") : hour < 18 ? __("Добрий день") : __("Добрий вечір");
	const first_name = (frappe.session.user_fullname || frappe.session.user).split(" ")[0];
	// moment has no uk locale in the desk bundle: the words are written here
	const DAYS = ["неділя", "понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота"];
	const MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"];
	const now = new Date();
	const date_text = `${__(DAYS[now.getDay()])}, ${now.getDate()} ${__(MONTHS[now.getMonth()])} ${now.getFullYear()}`;

	const SECTION_ICON = {
		"UA Sales Invoice": "trending",
		"UA Customer Order": "file",
		"UA Purchase Receipt": "cart",
		"UA Supplier Order": "file",
		"UA Cash Receipt": "cash",
		"UA Cash Payment": "landmark",
	};
	const quick = shell.QUICK_CREATE.filter((dt) => frappe.model.can_create(dt)).slice(0, 5);
	const tiles =
		quick
			.map((dt) => {
				const s = shell.section_of(dt);
				return (
					`<button type="button" class="ua-qtile" data-new="${esc(dt)}"><span class="ua-qicon">${icon(
						SECTION_ICON[dt] || "file"
					)}</span>` + `<span><b>${esc(__(dt))}</b><small>${esc(s ? __(s.label) : "")}</small></span></button>`
				);
			})
			.join("") +
		`<button type="button" class="ua-qtile ua-qtile--more" data-act="search"><span class="ua-qicon">${icon(
			"search"
		)}</span><span><b>${esc(__("Інший документ…"))}</b><small>${esc(__("Ctrl K — пошук"))}</small></span></button>`;

	const create_menu = () => {
		let html = "";
		shell.sections.forEach((s) => {
			const items = (s.quick || []).filter((c) => c.doctype && frappe.model.can_create(c.doctype));
			if (!items.length || s.id === "stock" || s.id === "catalogs") return;
			html += `<div class="ua-menu-label">${esc(__(s.label))}</div>`;
			html += items
				.map((c) => `<button class="ua-menu-item" data-new="${esc(c.doctype)}">${icon("file-plus")}${esc(__(c.label))}</button>`)
				.join("");
		});
		return html;
	};

	const CARD_DEFS = [
		{ key: "bank", label: __("Гроші на рахунках"), icon: "landmark" },
		{ key: "cash", label: __("Готівка в касі"), icon: "cash" },
		{ key: "receivable", label: __("Нам винні покупці"), icon: "user" },
		{ key: "payable", label: __("Ми винні постачальникам"), icon: "cart" },
	];
	const kpi_skeleton = CARD_DEFS.map(
		(c) =>
			`<div class="ua-card ua-kpi"><div class="ua-kpi-label">${icon(c.icon)}${esc(c.label)}</div>` +
			'<span class="ua-skel" style="width:60%;height:20px;margin-top:10px"></span><span class="ua-skel" style="width:40%;margin-top:10px"></span></div>'
	).join("");

	$root.html(`
		<div class="ua-ph">
			<div>
				<h1 class="ua-hello">${esc(hello)}, ${esc(first_name)}</h1>
				<p class="ua-ph-sub ua-home-sub">${esc([org && org.org_name, date_text].filter(Boolean).join(" · "))}</p>
			</div>
			<div class="ua-ph-actions">
				<button class="ua-btn ua-btn--primary" data-act="create" aria-haspopup="menu" aria-expanded="false">${icon(
					"plus"
				)}${esc(__("Створити"))}${icon("chev-d")}</button>
			</div>
		</div>
		<section aria-label="${esc(__("Швидке створення"))}"><div class="ua-quick">${tiles}</div></section>
		<section class="ua-kpis" aria-label="${esc(__("Залишки"))}">${kpi_skeleton}</section>
		<div class="ua-home-cols">
			<section class="ua-card" aria-labelledby="ua-r-title">
				<div class="ua-card-head">
					<h2 class="ua-card-title" id="ua-r-title">${esc(__("Останні документи"))}</h2>
					<div class="ua-right ua-row"><div class="ua-seg" role="tablist" aria-label="${esc(__("Фільтр"))}">
						<button role="tab" data-mode="all">${esc(__("Усі"))}</button><button role="tab" data-mode="mine">${esc(
							__("Мої")
						)}</button><button role="tab" data-mode="unposted">${esc(__("Не проведені"))}</button>
					</div></div>
				</div>
				<div class="ua-recent-body"></div>
			</section>
			<div class="ua-stack">
				<section class="ua-card ua-calendar" aria-labelledby="ua-c-title" hidden>
					<div class="ua-card-head"><h2 class="ua-card-title" id="ua-c-title">${esc(__("Календар бухгалтера"))}</h2></div>
					<div class="ua-card-body ua-cal-body"></div>
				</section>
				<section class="ua-card" aria-labelledby="ua-f-title">
					<div class="ua-card-head"><h2 class="ua-card-title" id="ua-f-title">${esc(__("Обране"))}</h2>
						<span class="ua-right ua-subtle ua-fav-count"></span></div>
					<div class="ua-card-body ua-fav-body"></div>
				</section>
				<section class="ua-card" aria-labelledby="ua-t-title">
					<div class="ua-card-head"><h2 class="ua-card-title" id="ua-t-title">${esc(__("Нагадування"))}</h2></div>
					<div class="ua-card-body ua-tasks"><span class="ua-skel" style="width:80%"></span><span class="ua-skel" style="width:50%;margin-top:10px"></span></div>
				</section>
			</div>
		</div>`);

	// ---------- favourites
	const favs = shell.favs();
	$root.find(".ua-fav-count").text(favs.length || "");
	$root.find(".ua-fav-body").html(
		favs.length
			? favs
					.map(
						(f, i) =>
							`<a class="ua-fav-item" href="#" data-fav-i="${i}"><span class="ua-fi">${icon(shell.fav_icon(f))}</span>` +
							`<span><span>${esc(f.label)}</span>${
								shell.fav_meta(f) ? `<small>${esc(shell.fav_meta(f))}</small>` : ""
							}</span>${icon("arrow-right", "ua-i-go")}</a>`
					)
					.join("")
			: ui.empty_html({
					art: "star",
					title: __("Обраного ще немає"),
					text: __("Додайте розділи в обране зірочкою в панелі функцій"),
					cls: "ua-empty--sm",
			  })
	);

	// ---------- balance cards and reminders
	const draw_dashboard = (d) => {
		const since = frappe.datetime.str_to_user(d.month_start);
		if (!d.cards) {
			$root.find(".ua-kpis").remove();
		} else {
			$root.find(".ua-kpis").html(
				CARD_DEFS.map((c) => {
					const v = d.cards[c.key] || { balance: 0, change: 0 };
					const ch = v.change;
					const meta = ch
						? `<span class="${(c.key === "payable" ? ch < 0 : ch > 0) ? "ua-up" : "ua-down"}">${ch > 0 ? "+" : "−"}${esc(
								ui.money(Math.abs(ch), { cur: true })
						  )}</span> ${esc(__("з {0}", [since]))}`
						: esc(__("Без змін з {0}", [since]));
					return (
						`<div class="ua-card ua-kpi"><div class="ua-kpi-label">${icon(
							c.icon
						)}${esc(c.label)}</div>` +
						`<div class="ua-kpi-val ua-num">${esc(ui.money(v.balance))}<span class="ua-cur">₴</span></div>` +
						`<div class="ua-kpi-meta">${meta}</div></div>`
					);
				}).join("")
			);
		}
		const tasks = (d.reminders || []).map((r) => {
			if (r.kind === "unposted") {
				return (
					`<a class="ua-task" href="#" data-act="unposted"><span class="ua-dot" style="background:var(--ua-warning)"></span><div>` +
					`${esc(__("Не проведено документів: {0}", [r.count]))}<small>${esc(__("Перевірте та проведіть їх"))}</small></div></a>`
				);
			}
			const days = r.days;
			return (
				`<div class="ua-task"><span class="ua-dot" style="background:var(--ua-${days <= 5 ? "danger" : "warning"})"></span><div>` +
				`${esc(__("Декларація з ПДВ за {0}", [r.month]))}<small>${esc(
					__("Подати до {0} · залишилось днів: {1}", [frappe.datetime.str_to_user(r.due), days])
				)}</small></div></div>`
			);
		});
		$root.find(".ua-tasks").html(
			tasks.length
				? tasks.join("")
				: ui.empty_html({ art: "check-circle", title: __("Нагадувань немає"), cls: "ua-empty--sm" })
		);
	};

	const dash_error = () => {
		$root.find(".ua-kpis").html(
			`<div class="ua-card ua-kpi-error">${ui.empty_html({
				error: true,
				title: __("Не вдалося завантажити залишки"),
				text: __("Перевірте з’єднання і спробуйте ще раз."),
				actions: [{ label: __("Повторити"), act: "retry", icon: "refresh" }],
				cls: "ua-empty--sm",
			})}</div>`
		);
		$root.find(".ua-tasks").html(ui.empty_html({ art: "check-circle", title: __("Нагадувань немає"), cls: "ua-empty--sm" }));
	};

	const load_dashboard = () =>
		frappe
			.xcall(METHOD + "get_dashboard", { organization: org ? org.name : null })
			.then(draw_dashboard)
			.catch(dash_error);

	// ---------- accountant calendar (overdue, today, upcoming); hidden for users without the role
	const CAL_METHOD = "ua_accounting.api.calendar.";
	const draw_calendar = (res) => {
		const task = (t, cls) =>
			`<div class="ua-task" data-task="${esc(t.name)}"><span class="ua-dot" style="background:var(--ua-${cls})"></span><div>` +
			`${esc(t.title)}<small>${
				cls === "danger"
					? `<b class="ua-down">${esc(__("Прострочено"))}</b> · `
					: ""
			}${esc(__("Строк"))}: ${esc(frappe.datetime.str_to_user(t.due_date))}</small></div>` +
			`<button type="button" class="ua-btn ua-btn--ghost ua-btn--sm ua-right" data-complete="${esc(t.name)}">${esc(__("Виконано"))}</button></div>`;
		const parts = [].concat(
			res.overdue.map((t) => task(t, "danger")),
			res.today.map((t) => task(t, "warning")),
			res.upcoming.map((t) => task(t, "info"))
		);
		$root.find(".ua-cal-body").html(
			parts.length
				? parts.join("")
				: ui.empty_html({ art: "check-circle", title: __("Завдань немає"), cls: "ua-empty--sm" })
		);
		$root.find(".ua-calendar").prop("hidden", false);
	};
	const load_calendar = () => {
		if (!org) return;
		frappe
			.call({ method: CAL_METHOD + "get_home", args: { organization: org.name }, silent: true })
			.then((r) => draw_calendar(r.message))
			.catch(() => $root.find(".ua-calendar").prop("hidden", true));
	};

	// ---------- recent documents
	const BADGE = {
		0: ["ua-badge--unposted", __("Не проведено")],
		1: ["ua-badge--posted", __("Проведено")],
		2: ["ua-badge--cancelled", __("Скасовано")],
	};
	const load_recent = () => {
		const $b = $root.find(".ua-recent-body");
		$root.find(".ua-seg button").each(function () {
			$(this).toggleClass("is-on", $(this).attr("data-mode") === state.mode).attr("aria-selected", $(this).attr("data-mode") === state.mode);
		});
		$b.html(ui.skeleton_rows(7, [12, 30, 26, 14, 12]));
		frappe
			.xcall(METHOD + "get_recent", { organization: org ? org.name : null, mode: state.mode })
			.then((rows) => {
				state.rows = rows;
				if (!rows.length) {
					$b.html(
						ui.empty_html({
							art: "inbox",
							title: state.mode === "unposted" ? __("Усі документи проведено") : __("Документів ще немає"),
							text: state.mode === "unposted" ? "" : __("Створіть перший документ кнопкою «Створити»."),
							cls: "ua-empty--sm",
						})
					);
					return;
				}
				$b.html(
					`<div class="ua-table-wrap"><table class="ua-table ua-table--tall ua-recent"><thead><tr><th>${esc(
						__("Дата")
					)}</th><th>${esc(__("Документ"))}</th><th>${esc(__("Контрагент"))}</th><th class="ua-r">${esc(
						__("Сума, ₴")
					)}</th><th>${esc(__("Статус"))}</th></tr></thead><tbody>` +
						rows
							.map((r, i) => {
								const b = BADGE[r.docstatus] || BADGE[0];
								const cur = r.currency && r.currency !== "UAH" ? ` <span class="ua-cur">${esc(r.currency)}</span>` : "";
								return (
									`<tr data-i="${i}" tabindex="0"><td class="ua-num ua-muted">${esc(
										r.posting_date ? frappe.datetime.str_to_user(r.posting_date) : ""
									)}</td>` +
									`<td><span class="ua-doc-type">${esc(__(r.doctype))}</span><span class="ua-cell-sub">${esc(r.name)}</span></td>` +
									`<td>${esc(r.counterparty || "")}</td>` +
									`<td class="ua-r ua-num ua-cell-main">${r.amount ? esc(ui.money(r.amount)) + cur : ""}</td>` +
									`<td><span class="ua-badge ${b[0]}">${esc(b[1])}</span></td></tr>`
								);
							})
							.join("") +
						"</tbody></table></div>"
				);
			})
			.catch(() => {
				$b.html(
					ui.empty_html({
						error: true,
						title: __("Не вдалося завантажити документи"),
						text: __("Перевірте з’єднання і спробуйте ще раз."),
						actions: [{ label: __("Повторити"), act: "retry-recent", icon: "refresh" }],
						cls: "ua-empty--sm",
					})
				);
			});
	};

	load_dashboard();
	load_calendar();
	load_recent();

	// ---------- events
	$root.off(".ua_home");
	$root.on("click.ua_home", "[data-new]", function () {
		frappe.new_doc($(this).attr("data-new"));
	});
	$root.on("click.ua_home", "[data-act]", function (e) {
		const act = $(this).attr("data-act");
		if (act === "search") shell.open_search();
		if (act === "create") {
			ui.menu(this, create_menu(), (item) => {
				const dt = item.getAttribute("data-new");
				if (dt) frappe.new_doc(dt);
			}, { align: "right", cls: "ua-create-pop" });
		}
		if (act === "retry") load_dashboard();
		if (act === "retry-recent") load_recent();
		if (act === "unposted") {
			e.preventDefault();
			state.mode = "unposted";
			load_recent();
		}
	});
	$root.on("click.ua_home", ".ua-seg button", function () {
		state.mode = $(this).attr("data-mode");
		load_recent();
	});
	$root.on("click.ua_home keydown.ua_home", ".ua-recent tbody tr", function (e) {
		if (e.type === "keydown" && e.key !== "Enter") return;
		const r = (state.rows || [])[+$(this).attr("data-i")];
		if (r) frappe.set_route("Form", r.doctype, r.name);
	});
	$root.on("click.ua_home", "[data-complete]", function () {
		frappe.xcall(CAL_METHOD + "complete", { name: $(this).attr("data-complete") }).then(load_calendar);
	});
	$root.on("click.ua_home", "[data-fav-i]", function (e) {
		e.preventDefault();
		const f = shell.favs()[+$(this).attr("data-fav-i")];
		if (f) shell.open_fav(f);
	});
};
