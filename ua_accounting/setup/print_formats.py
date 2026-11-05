"""Print forms of the primary documents (T-436, T-447).

The forms are Jinja print formats. They are created on install and migrate, and the text
of a form is refreshed each time (like the print style), unless a user changed it.
"""

import hashlib

import frappe

STYLE = """<style>
.ua-form { font-size: 12px; color: #111; }
.ua-form h2 { font-size: 16px; margin: 0 0 4px; }
.ua-form .meta { margin-bottom: 10px; }
.ua-form table { width: 100%; border-collapse: collapse; margin: 8px 0; }
.ua-form th, .ua-form td { border: 1px solid #333; padding: 3px 6px; }
.ua-form th { background: #eee; text-align: center; }
.ua-form td.n, .ua-form th.n { text-align: right; white-space: nowrap; }
.ua-form .total { text-align: right; margin: 2px 0; }
.ua-form .sign { margin-top: 28px; }
.ua-form .sign td { border: 0; padding: 14px 6px 0; }
.ua-form .ref { color: #777; font-size: 10px; margin-top: 6px; }
.ua-form table.plain th, .ua-form table.plain td { border: 0; background: none; text-align: left; }
.ua-form td.logo { width: 90px; }
.ua-form td.logo img { max-height: 60px; max-width: 90px; }
.ua-form .cancel { color: #b00; font-weight: bold; }
.ua-form .words { margin: 6px 0; }
.ua-form .qr { text-align: right; margin: 6px 0; }
.ua-form .qr img { width: 80px; height: 80px; }
.ua-form .cut { border-top: 1px dashed #333; margin: 18px 0 10px; }
</style>"""

MACROS = """{% macro party(label, p) %}<div>{{ label }}: <b>{{ (p.title or "")|e }}</b>{% if p.edrpou %}, код ЄДРПОУ {{ p.edrpou|e }}{% endif %}{% if p.ipn %}, ІПН {{ p.ipn|e }}{% endif %}{% if p.legal_address %}, {{ p.legal_address|e }}{% endif %}{% if p.phone %}, тел. {{ p.phone|e }}{% endif %}</div>{% endmacro %}
{% macro bank(b) %}{% if b and b.iban %}<div>Р/р {{ b.iban|e }}{% if b.bank_name %}, {{ b.bank_name|e }}{% endif %}{% if b.mfo %}, МФО {{ b.mfo|e }}{% endif %}</div>{% endif %}{% endmacro %}
{% macro head(title) %}<table class="plain"><tr><td class="logo">{% if org.logo %}<img src="{{ org.logo|e }}">{% endif %}</td>
<td><h2>{{ title }}</h2>{% if doc.docstatus == 2 %}<div class="cancel">Скасовано</div>{% endif %}</td></tr></table>{% endmacro %}
{% macro sign(left, right) %}<table class="sign"><tr><td>{{ left }}</td><td>Директор ________________ {{ (org.director_name or "")|e }}</td>
<td>Головний бухгалтер ________________ {{ (org.accountant_name or "")|e }}</td><td>{{ right }}</td></tr></table><div>М.П.</div>{% endmacro %}
{% macro money(value, currency) %}{{ uk_money(value) }} {{ "грн" if (not currency or currency == "UAH") else currency|e }}{% endmacro %}
{% macro qr(payload) %}<div class="qr"><img src="{{ qr_code(payload) }}" alt="QR" width="80" height="80"></div>{% endmacro %}
"""

SETUP = '{% set org = org_info(doc.organization) %}{% set cp = party_info(doc.counterparty) %}'


def form(title, *parts, date="doc.posting_date", number="doc.name|e", pre=""):
    """A form: styles, macros, the heading with logo and the parts."""
    return (STYLE + MACROS + SETUP + pre + '<div class="ua-form">{{ head("' + title + ' № " ~ ' + number + ' ~ " від " ~ uk_date('
            + date + ")) }}" + "".join(parts) + "</div>")


# The primary documents of an event of the Invoice (waybill, TTN, act) print the chosen event: api.invoice.print_event
# puts it in `doc.print_event` (its own number, date, lines and totals). Without it the form asks to choose one.
EVENT = "{% set ev = doc.print_event %}"
EVENT_FORM = dict(
    date="(ev.posting_date if ev else doc.posting_date)", number='(ev.number if ev else "")|e', pre=EVENT
)


def event_form(title, *parts):
    """A form of an event: the Invoice is the basis, the event gives the number, the date and the lines."""
    body = '{% if not ev %}<p>Оберіть подію інвойсу для друку</p>{% else %}' + "".join(parts) + "{% endif %}"
    return form(title, body, **EVENT_FORM)



ROWS = """
{% set rows = (doc.goods or []) + (doc.services or []) %}
<table>
<tr><th>№</th><th>Найменування</th><th>Од.</th><th class="n">Кількість</th><th class="n">Ціна</th>
<th class="n">Знижка, %</th><th class="n">Сума без ПДВ</th><th class="n">ПДВ</th><th class="n">Всього</th></tr>
{% for r in rows %}
<tr><td>{{ loop.index }}</td><td>{{ (r.item_name or r.item or "")|e }}</td><td>{{ (r.uom or "")|e }}</td>
<td class="n">{{ r.quantity }}</td><td class="n">{{ uk_money(r.price) }}</td>
<td class="n">{{ r.discount_percent or 0 }}</td><td class="n">{{ uk_money(r.amount) }}</td>
<td class="n">{{ uk_money(r.vat_amount) }}</td><td class="n">{{ uk_money(r.total) }}</td></tr>
{% endfor %}
</table>
<div class="total">Разом без ПДВ: <b>{{ uk_money(doc.total_net) }}</b></div>
<div class="total">ПДВ: <b>{{ uk_money(doc.vat_total) }}</b></div>
<div class="total">Всього до сплати: <b>{{ uk_money(doc.total_amount) }}</b></div>
<p class="words">Всього на суму: <b>{{ money_in_words(doc.total_amount, doc.currency) }}</b></p>
"""

EVENT_ROWS = """
{% set rows = ev.lines %}
<table>
<tr><th>№</th><th>Найменування</th><th>Од.</th><th class="n">Кількість</th><th class="n">Ціна</th>
<th class="n">Знижка, %</th><th class="n">Сума без ПДВ</th><th class="n">ПДВ</th><th class="n">Всього</th></tr>
{% for r in rows %}
<tr><td>{{ loop.index }}</td><td>{{ (r.item_name or r.item or "")|e }}</td><td>{{ (r.uom or "")|e }}</td>
<td class="n">{{ r.quantity }}</td><td class="n">{{ uk_money(r.price) }}</td>
<td class="n">{{ r.discount_percent or 0 }}</td><td class="n">{{ uk_money(r.amount) }}</td>
<td class="n">{{ uk_money(r.vat_amount) }}</td><td class="n">{{ uk_money(r.total) }}</td></tr>
{% endfor %}
{% for r in ev.packaging %}
<tr><td></td><td>Тара: {{ (r.item_name or r.item or "")|e }}</td><td>{{ (r.uom or "")|e }}</td>
<td class="n">{{ r.quantity }}</td><td class="n">{{ uk_money(r.price) }}</td><td></td><td></td><td></td><td class="n">{{ uk_money(r.amount) }}</td></tr>
{% endfor %}
</table>
<div class="total">Разом без ПДВ: <b>{{ uk_money(ev.total_net) }}</b></div>
<div class="total">ПДВ: <b>{{ uk_money(ev.vat_total) }}</b></div>
<div class="total">Всього до сплати: <b>{{ uk_money(ev.total_amount) }}</b></div>
<p class="words">Всього на суму: <b>{{ money_in_words(ev.total_amount, doc.currency) }}</b></p>
"""

REF = '<div class="ref">Довідково: код контрагента в системі {{ (doc.counterparty or "")|e }}</div>'

SELLER = '{{ party("Постачальник", org) }}{{ bank(org.bank) }}{{ party("Покупець", cp) }}'
CONTRACT = '{% if doc.contract %}<div>Договір: {{ doc.contract|e }}</div>{% endif %}'
# an event names the Invoice as its basis (T-533, T-705)
INVOICE_BASIS = '<div>Підстава: рахунок № {{ doc.name|e }} від {{ uk_date(doc.posting_date) }}</div>'
TERMS = ('{% if doc.due_date %}<div>Оплатити до: {{ uk_date(doc.due_date) }}</div>{% endif %}'
         '{% if doc.payment_terms %}<div>Умови розрахунків: {{ doc.payment_terms|e }}</div>{% endif %}')

INVOICE = form("Рахунок на оплату", '<div class="meta">', SELLER, CONTRACT, TERMS, "</div>", ROWS,
               '{{ qr("UA-INV:" ~ doc.name ~ "|" ~ doc.posting_date ~ "|" ~ doc.total_amount) }}',
               '{{ sign("", "") }}', REF)

ACT_WORKS = event_form(
    "Акт виконаних робіт",
    '<div class="meta">{{ party("Виконавець", org) }}{{ party("Замовник", cp) }}', CONTRACT, INVOICE_BASIS, "</div>", EVENT_ROWS,
    "<p>Зазначені послуги виконано в повному обсязі. Замовник претензій до обсягу, якості та строків "
    "надання послуг не має.</p>", '{{ sign("Виконавець", "Замовник ________________") }}', REF)

SALES_INVOICE = event_form(
    "Видаткова накладна",
    '<div class="meta">', SELLER, CONTRACT, INVOICE_BASIS,
    '{% if ev.warehouse %}<div>Склад: {{ title_of("UA Warehouse", ev.warehouse)|e }}</div>{% endif %}</div>',
    EVENT_ROWS, '{{ qr("UA-INV:" ~ ev.number ~ "|" ~ ev.posting_date ~ "|" ~ ev.total_amount) }}',
    '{{ sign("Відвантажив", "Отримав ________________") }}', REF)

RECEIPT = form(
    "Прибуткова накладна",
    '<div class="meta">{{ party("Постачальник", cp) }}{{ party("Одержувач", org) }}', CONTRACT,
    '{% if doc.warehouse %}<div>Склад: {{ title_of("UA Warehouse", doc.warehouse)|e }}</div>{% endif %}</div>',
    ROWS, '{{ sign("Здав ________________", "Прийняв ________________") }}', REF)

# Tax invoice (ПН) of the document UA Tax Invoice: its own lines, the registration in ЄРПН and the basis (T-533)
TAX_INVOICE_DOC = form(
    "Податкова накладна",
    """<div class="meta">{{ party("Постачальник (продавець)", org) }}{{ party("Одержувач (покупець)", cp) }}
<div>Дата складення: {{ uk_date(doc.posting_date) }}, номер: {{ (doc.number or doc.name)|e }}</div>
<div>Вид: {{ (doc.invoice_kind or "")|e }}{% if doc.contract %}, договір: {{ doc.contract|e }}{% endif %}</div>
{% if doc.basis %}<div>Підстава: {{ (doc.basis_type or "")|e }} {{ doc.basis|e }}</div>{% endif %}</div>
<table>
<tr><th>№</th><th>Номенклатура постачання</th><th>Код УКТЗЕД</th><th>Од.</th><th class="n">Кількість</th>
<th class="n">Ціна без ПДВ</th><th class="n">Ставка ПДВ, %</th><th class="n">Обсяг постачання без ПДВ</th>
<th class="n">Сума ПДВ</th></tr>
{% for r in doc.lines %}
<tr><td>{{ loop.index }}</td><td>{{ (r.description or "")|e }}</td><td>{{ (r.ukt_zed or "")|e }}</td>
<td>{{ (r.uom or "")|e }}</td><td class="n">{{ r.quantity }}</td><td class="n">{{ uk_money(r.price) }}</td>
<td class="n">{{ (r.vat_rate or "")|e }}</td><td class="n">{{ uk_money(r.base_amount) }}</td>
<td class="n">{{ uk_money(r.vat_amount) }}</td></tr>
{% endfor %}
</table>
<div class="total">Усього обсяг постачання без ПДВ: <b>{{ uk_money(doc.total_base) }}</b></div>
<div class="total">Сума ПДВ: <b>{{ uk_money(doc.total_vat) }}</b></div>
<div class="total">Усього з ПДВ: <b>{{ uk_money(doc.total_amount) }}</b></div>
<p class="words">Усього з ПДВ прописом: <b>{{ money_in_words(doc.total_amount, doc.currency) }}</b></p>
<div>Реєстрація в ЄРПН: {{ (doc.erpn_status or "")|e }}{% if doc.erpn_reg_number %}, реєстраційний номер {{ doc.erpn_reg_number|e }}{% endif %}{% if doc.erpn_reg_date %} від {{ uk_date(doc.erpn_reg_date) }}{% endif %}</div>
""", '{{ sign("", "") }}', REF)

WAYBILL = event_form(
    "Товарно-транспортна накладна",
    """<div class="meta">{{ party("Вантажовідправник", org) }}{{ bank(org.bank) }}{{ party("Вантажоодержувач", cp) }}
<div>Пункт навантаження: {{ (org.legal_address or "")|e }}</div>
<div>Пункт розвантаження: {{ (cp.legal_address or "")|e }}</div>
""" + INVOICE_BASIS + """
<div>Автомобіль: {{ (ev.vehicle_no or "")|e }}</div>
<div>Водій: {{ (ev.driver_name or "")|e }}</div></div>
{% set rows = ev.lines %}
<table>
<tr><th>№</th><th>Найменування вантажу</th><th>Од.</th><th class="n">Кількість</th><th class="n">Ціна</th>
<th class="n">Сума з ПДВ</th></tr>
{% for r in rows %}
<tr><td>{{ loop.index }}</td><td>{{ (r.item_name or r.item or "")|e }}</td><td>{{ (r.uom or "")|e }}</td>
<td class="n">{{ r.quantity }}</td><td class="n">{{ uk_money(r.price) }}</td><td class="n">{{ uk_money(r.total) }}</td></tr>
{% endfor %}
</table>
<div class="total">Всього: <b>{{ uk_money(ev.total_amount) }}</b></div>
<p class="words">Вартість вантажу: <b>{{ money_in_words(ev.total_amount, doc.currency) }}</b></p>
""", '{{ sign("Відправник ________________", "Водій ________________") }}',
    "<div>Вантаж одержав ________________</div>", REF)

# --- cash and bank documents. Their head has no counterparty-based setup, so they build the text directly.

CASH_SETUP = (
    '{% set payer = party_info(doc.counterparty).title if doc.counterparty else person_name(doc.person) %}'
    '{% set foreign = doc.currency and doc.currency != "UAH" %}'
    '{% set base = (doc.amount or 0) * (doc.exchange_rate or 1) if foreign else doc.amount %}'
)
CASH_BASIS = '{{ (doc.operation_type or "")|e }}{% if doc.comment %}. {{ doc.comment|e }}{% endif %}'
CASH_SUM = """<div>Сума: <b>{{ money(doc.amount, doc.currency) }}</b></div>
<p class="words"><b>{{ money_in_words(doc.amount, doc.currency) }}</b></p>
{% if foreign %}<div>Еквівалент у гривнях за курсом {{ doc.exchange_rate }}: {{ uk_money(base) }} грн ({{ money_in_words(base) }})</div>{% endif %}"""


def cash_form(title, who, kind_left, kind_right, receipt):
    body = (CASH_SETUP + '<div class="meta">{{ party("Організація", org) }}<div>' + who + ': <b>{{ (payer or "")|e }}</b></div>'
            "<div>Підстава: " + CASH_BASIS + "</div>" + CASH_SUM + "</div>"
            '{{ sign("' + kind_left + '", "' + kind_right + '") }}')
    return form(title, body, receipt, REF)


PKO_RECEIPT = """<div class="cut"></div>
<div><b>Квитанція</b> до прибуткового касового ордера № {{ doc.name|e }} від {{ uk_date(doc.posting_date) }}</div>
<div>{{ (org.title or "")|e }}, код ЄДРПОУ {{ (org.edrpou or "")|e }}</div>
<div>Прийнято від: {{ (payer or "")|e }}</div>
<div>Сума: {{ money(doc.amount, doc.currency) }}</div>
<div>{{ money_in_words(doc.amount, doc.currency) }}</div>
{% if foreign %}<div>Еквівалент у гривнях: {{ uk_money(base) }} грн</div>{% endif %}
<div>Головний бухгалтер ________________ {{ (org.accountant_name or "")|e }}. Касир ________________ М.П.</div>"""

PKO = cash_form("Прибутковий касовий ордер", "Прийнято від", "Касир ________________", "", PKO_RECEIPT)
VKO = cash_form("Видатковий касовий ордер", "Видати (одержувач)", "Керівник", "Одержав ________________", "")

PAYMENT_ORDER = form(
    "Платіжне доручення",
    """{% set incoming = doc.direction == "Вхідне" %}
{% set mine = bank_info(doc.bank_account) %}{% set theirs = cp.bank %}
<div class="meta">
<div><b>Платник</b>:
{% if incoming %}{{ (cp.title or "")|e }}, код ЄДРПОУ {{ (cp.edrpou or "")|e }}{{ bank(theirs) }}
{% else %}{{ (org.title or "")|e }}, код ЄДРПОУ {{ (org.edrpou or "")|e }}{{ bank(mine) }}{% endif %}</div>
<div><b>Одержувач</b>:
{% if incoming %}{{ (org.title or "")|e }}, код ЄДРПОУ {{ (org.edrpou or "")|e }}{{ bank(mine) }}
{% else %}{{ (cp.title or "")|e }}, код ЄДРПОУ {{ (cp.edrpou or "")|e }}{{ bank(theirs) }}{% endif %}</div>
{{ party("Організація", org) }}
{% if doc.contract %}<div>Договір: {{ doc.contract|e }}</div>{% endif %}
<div>Сума: <b>{{ money(doc.amount, doc.currency) }}</b></div>
<p class="words"><b>{{ money_in_words(doc.amount, doc.currency) }}</b></p>
<div>Призначення платежу: {{ (doc.purpose or "")|e }}</div>
{% if doc.vat_amount %}<div>у т.ч. ПДВ: {{ uk_money(doc.vat_amount) }}</div>{% endif %}
</div>""", '{{ sign("", "") }}', REF)

POWER_OF_ATTORNEY = (
    STYLE + MACROS + '{% set org = org_info(doc.organization) %}{% set cp = party_info(doc.counterparty) %}'
    '<div class="ua-form">{{ head("Довіреність № " ~ doc.name|e ~ " від " ~ uk_date(doc.posting_date)) }}'
    """<div class="meta"><div><b>Дійсна до {{ uk_date(doc.valid_until) }}</b></div>
{{ party("Організація", org) }}
<div>Видана: <b>{{ person_name(doc.person)|e }}</b>, документ: {{ (doc.person_document or "")|e }}</div>
{% if doc.counterparty %}<div>На отримання цінностей від: <b>{{ (cp.title or "")|e }}</b></div>{% endif %}
<div>Підстава: {{ (doc.basis or "")|e }}</div></div>
<table><tr><th>№</th><th>Найменування цінностей</th><th>Од.</th><th class="n">Кількість</th></tr>
{% for r in doc.get("items") %}<tr><td>{{ loop.index }}</td><td>{{ (r.item_name or "")|e }}</td><td>{{ (r.uom or "")|e }}</td>
<td class="n">{{ r.quantity }}</td></tr>{% endfor %}</table>
<div>Підпис особи, що отримала довіреність, ________________ засвідчуємо.</div>
{{ sign("", "") }}""" + REF + "</div>")

RECONCILIATION = form(
    "Акт звірки взаєморозрахунків",
    """<div class="meta">
<div>за період з {{ uk_date(doc.date_from) }} по {{ uk_date(doc.date_to) }}</div>
{{ party("Організація", org) }}{{ party("Контрагент", cp) }}
<div>Ми, що нижче підписалися, {{ (org.title or "")|e }}, з одного боку, та {{ (cp.title or "")|e }}, з другого боку, склали цей акт про те,
що стан взаєморозрахунків за даними обліку такий:</div>
</div>
<table>
<tr><th>Дата</th><th>Документ</th><th class="n">Дебет</th><th class="n">Кредит</th></tr>
<tr><td colspan="2">Сальдо на {{ uk_date(doc.date_from) }}</td><td class="n" colspan="2">{{ uk_money(doc.opening_balance) }}</td></tr>
{% for r in doc.rows %}
<tr><td>{{ uk_date(r.posting_date) }}</td><td>{{ (r.document_type or "")|e }} {{ (r.document or "")|e }}</td>
<td class="n">{{ uk_money(r.debit) }}</td><td class="n">{{ uk_money(r.credit) }}</td></tr>
{% endfor %}
<tr><th colspan="2">Обороти за період</th><th class="n">{{ uk_money(doc.turnover_debit) }}</th>
<th class="n">{{ uk_money(doc.turnover_credit) }}</th></tr>
<tr><th colspan="2">Сальдо на {{ uk_date(doc.date_to) }}</th><th class="n" colspan="2">{{ uk_money(doc.closing_balance) }}</th></tr>
</table>
<p>За даними {{ (org.title or "")|e }}: {% if doc.closing_balance >= 0 %}заборгованість {{ (cp.title or "")|e }} на користь {{ (org.title or "")|e }}
{% else %}заборгованість {{ (org.title or "")|e }} на користь {{ (cp.title or "")|e }}{% endif %} на суму
<b>{{ money_in_words(doc.closing_balance|abs) }}</b> ({{ uk_money(doc.closing_balance|abs) }} грн).</p>
{% if doc.their_balance %}<p>За даними контрагента: {{ uk_money(doc.their_balance) }} грн. Розбіжність: {{ uk_money(doc.discrepancy) }} грн.</p>{% endif %}
{{ sign("", "Контрагент: Директор ________________ Головний бухгалтер ________________ М.П.") }}""", REF,
    date="doc.date_to")

FORMATS = (
    ("UA Видаткова накладна", "UA Payment Invoice", SALES_INVOICE),
    ("UA Рахунок на оплату", "UA Payment Invoice", INVOICE),
    ("UA Акт виконаних робіт", "UA Payment Invoice", ACT_WORKS),
    ("UA Податкова накладна (ПН)", "UA Tax Invoice", TAX_INVOICE_DOC),
    ("UA ТТН", "UA Payment Invoice", WAYBILL),
    ("UA ПКО", "UA Cash Receipt", PKO),
    ("UA ВКО", "UA Cash Payment", VKO),
    ("UA Платіжне доручення", "UA Payment Order", PAYMENT_ORDER),
    ("UA Довіреність", "UA Power of Attorney", POWER_OF_ATTORNEY),
    ("UA Прибуткова накладна", "UA Purchase Receipt", RECEIPT),
    ("UA Акт звірки", "UA Reconciliation Act", RECONCILIATION),
)


HASH_KEY = "ua_print_format_hash:"


def _hash(html):
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


OBSOLETE = ("UA Податкова накладна",)  # the sale tax invoice form: the ПН is the document UA Tax Invoice


def run():
    for name in OBSOLETE:
        if frappe.db.exists("Print Format", name):
            frappe.delete_doc("Print Format", name, force=True, ignore_permissions=True)
            frappe.db.delete("DefaultValue", {"defkey": HASH_KEY + name})
    # a cancelled document prints with the mark «Скасовано» instead of an error
    frappe.db.set_single_value("Print Settings", "allow_print_for_cancelled", 1)
    for name, doctype, html in FORMATS:
        if frappe.db.exists("Print Format", name):
            # rewrite only a format that still equals the last generated version;
            # a format edited or disabled by a user is left alone
            key = HASH_KEY + name
            stored = frappe.db.get_default(key)
            current = frappe.db.get_value("Print Format", name, "html") or ""
            if stored is None or _hash(current) == stored:
                frappe.db.set_value(
                    "Print Format", name, {"html": html, "doc_type": doctype, "standard": "No", "custom_format": 1},
                    update_modified=False,
                )
                frappe.db.set_default(key, _hash(html))
            continue
        doc = frappe.get_doc(
            {
                "doctype": "Print Format",
                "name": name,
                "doc_type": doctype,
                "module": "UA Documents",
                "print_format_type": "Jinja",
                "custom_format": 1,
                "standard": "No",
                "html": html,
                "disabled": 0,
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert()
        frappe.db.set_default(HASH_KEY + name, _hash(html))
