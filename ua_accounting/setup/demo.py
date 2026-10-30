"""Demo data generator.

Fills a site with a Ukrainian trade company: catalogs, opening balances and
posted documents for the last months. The same seed gives the same data
(names, amounts, dates, document numbers). Record ids of catalogs are random.

Run (from the bench folder):
    bench --site ua-dev.localhost ua-demo --scale small
    bench --site ua-dev.localhost ua-demo --reset
    bench --site ua-dev.localhost execute ua_accounting.setup.demo.make_demo --kwargs "{'scale': 'small'}"

Every record that the generator creates gets the tag `ua-demo` (field
`_user_tags`). `--reset` cancels and deletes only tagged records.
Currency rates of USD and EUR stay (they are not tagged).
"""

import datetime
import random

import frappe
from frappe.utils import add_months, flt, get_first_day, getdate, today

TAG = "ua-demo"
ORG_NAME = "ТОВ «Демо Трейд»"

# docs_per_day: average number of documents on one business day
SCALES = {
    "small": {
        "items": 200,
        "counterparties": 30,
        "months": 3,
        "docs_per_day": 8.5,
        "opening_stock_items": 110,
        "fast_items": False,
    },
    "large": {
        "items": 100000,
        "counterparties": 2000,
        "months": 3,
        "docs_per_day": 1000,
        "opening_stock_items": 4000,
        "fast_items": True,
    },
}

# documents are cancelled in this order (links go from the last to the first)
DOC_ORDER = [
    "UA Cash Payment",
    "UA Cash Receipt",
    "UA Sales Invoice",
    "UA Customer Order",
    "UA Purchase Receipt",
    "UA Supplier Order",
    "UA Journal Operation",
]
# catalogs are deleted in this order; "tree" ones from the leaves up
CATALOG_ORDER = [
    ("UA Counterparty Contract", False),
    ("UA Counterparty", True),
    ("UA Item", True),
    ("UA Warehouse", False),
    ("UA Department", True),
    ("UA Bank Account", False),
    ("UA Cash Desk", False),
    ("UA Fixed Asset", False),
    ("UA Intangible Asset", False),
    ("UA Low Value Asset", False),
    ("UA Person", False),
    ("UA Cash Flow Item", True),
    ("UA Expense Item", False),
    ("UA Bank", False),
    ("UA Organization", False),
]

# ------------------------------------------------------------------ static data

BANKS = [
    ("305299", "АТ КБ «ПриватБанк»", "14360570", "Київ"),
    ("300465", "АТ «Ощадбанк»", "00032129", "Київ"),
    ("322001", "АТ «Universal Bank»", "21133352", "Київ"),
    ("334851", "АТ «ПУМБ»", "14282829", "Київ"),
]

CITIES = ["Київ", "Львів", "Дніпро", "Одеса", "Харків", "Полтава", "Вінниця", "Івано-Франківськ", "Запоріжжя", "Чернівці"]
STREETS = ["вул. Шевченка", "вул. Грушевського", "просп. Свободи", "вул. Лесі Українки", "вул. Франка", "вул. Соборна",
           "вул. Миру", "вул. Центральна", "вул. Незалежності", "вул. Промислова"]

PERSONS = {
    "director": "Коваленко Андрій Петрович",
    "accountant": "Мельник Олена Іванівна",
    "cashier": "Шевченко Ірина Василівна",
    "keeper1": "Бондар Максим Олегович",
    "keeper2": "Ткачук Наталія Степанівна",
}

DEPARTMENTS = [("Адміністрація", None), ("Відділ продажів", None), ("Роздрібні продажі", "Відділ продажів"),
               ("Склад", None), ("Бухгалтерія", None)]

WAREHOUSES = [("Основний склад", "Оптовий", "Склад", "keeper1", 0.6),
              ("Магазин «Центр»", "Роздрібний", "Роздрібні продажі", "keeper2", 0.3),
              ("Склад №2 (Одеса)", "Оптовий", "Склад", "keeper1", 0.1)]

CASH_FLOW_ITEMS = [
    ("Операційна діяльність", None),
    ("Оплата від покупців", "Операційна діяльність"),
    ("Оплата постачальникам", "Операційна діяльність"),
    ("Оренда та комунальні послуги", "Операційна діяльність"),
    ("Господарські витрати", "Операційна діяльність"),
    ("Фінансова діяльність", None),
    ("Внески засновників", "Фінансова діяльність"),
]

EXPENSE_ITEMS = [
    ("Оренда приміщення", "Інші"),
    ("Зв'язок та інтернет", "Інші"),
    ("Реклама та маркетинг", "Інші"),
    ("Транспортні витрати", "Інші"),
    ("Господарські матеріали", "Матеріальні затрати"),
    ("Заробітна плата", "Оплата праці"),
    ("Єдиний соціальний внесок", "Відрахування на соціальні заходи"),
    ("Амортизація", "Амортизація"),
]

# name, role, kind, extra: "goods" / "service" / "foreign:<cur>" / "export:<cur>"
COUNTERPARTIES = [
    ("ТОВ «Техно-Імпорт Київ»", "supplier", "Юридична особа", "goods"),
    ("ТОВ «Електроніка Опт»", "supplier", "Юридична особа", "goods"),
    ("ПП «ГаджетПостач»", "supplier", "Юридична особа", "goods"),
    ("ТОВ «Домашній Комфорт Груп»", "supplier", "Юридична особа", "goods"),
    ("ТОВ «Офіс-Центр»", "supplier", "Юридична особа", "goods"),
    ("ТОВ «Канцлер Опт»", "supplier", "Юридична особа", "goods"),
    ("ТОВ «МедТехСервіс»", "supplier", "Юридична особа", "goods"),
    ("ТОВ «Сувенір-Сервіс»", "supplier", "Юридична особа", "goods"),
    ("ТОВ «Нерухомість-Інвест»", "supplier", "Юридична особа", "service:rent"),
    ("ТОВ «Телеком Україна Плюс»", "supplier", "Юридична особа", "service:telecom"),
    ("ТОВ «Рекламна Агенція Промінь»", "supplier", "Юридична особа", "service:ads"),
    ("TechSource Components Ltd", "supplier", "Юридична особа", "foreign:USD"),
    ("ТОВ «Ромашка Рітейл»", "customer", "Юридична особа", ""),
    ("ТОВ «Київ-Маркет»", "customer", "Юридична особа", ""),
    ("ПП «Дніпро Трейд»", "customer", "Юридична особа", ""),
    ("ТОВ «Львівська Торгова Компанія»", "customer", "Юридична особа", ""),
    ("ТОВ «Одеса Електро»", "customer", "Юридична особа", ""),
    ("ФОП Бондаренко Тетяна Миколаївна", "customer", "ФОП", ""),
    ("ТОВ «Харків Офіс Сервіс»", "customer", "Юридична особа", ""),
    ("ТОВ «Карпати Ритейл»", "customer", "Юридична особа", ""),
    ("ТОВ «Південна Логістика»", "customer", "Юридична особа", ""),
    ("ПП «Затишний Дім»", "customer", "Юридична особа", ""),
    ("ТОВ «Школа Майбутнього»", "customer", "Юридична особа", ""),
    ("КНП «Міська лікарня №5»", "customer", "Юридична особа", ""),
    ("ТОВ «Стар-Мобайл»", "customer", "Юридична особа", ""),
    ("ФОП Савченко Віктор Олексійович", "customer", "ФОП", ""),
    ("Nordic Retail GmbH", "customer", "Юридична особа", "export:EUR"),
    ("ГУ ДПС у місті Києві", "other", "Юридична особа", ""),
    ("ПрАТ «Страхова компанія Гарант»", "other", "Юридична особа", ""),
    ("ФОП Лисенко Дмитро Валерійович", "other", "ФОП", ""),
]
EXTRA_WORDS_A = ["Альфа", "Омега", "Прогрес", "Верес", "Лотос", "Сигма", "Зоря", "Ватра", "Горизонт", "Мрія", "Вектор", "Нива"]
EXTRA_WORDS_B = ["Трейд", "Опт", "Груп", "Сервіс", "Логістик", "Дистрибуція", "Маркет", "Сталь", "Плюс", "Холдинг"]

BRANDS = ["Nova", "Veltra", "Orion", "Kvant", "Lumex", "Zefir", "Tekno", "Alta"]
MODELS = ["X5", "Pro 14", "Lite", "S200", "Max", "Air", "Neo", "One", "Plus", "Go", "T7", "Prime"]
SIZES = ["синій", "чорний", "червоний", "зелений", "А4", "А5", "80 г/м²", "Premium", "Standard", "Економ"]
OWN_VARIANTS = ["міні", "стандарт", "преміум", "святковий", "офісний", "подарунковий"]

# key, folder, type, uom, vat rate, article prefix, share of the items, variants, [(name, price from, price to)]
ITEM_GROUPS = [
    ("el", "Електроніка", "Товар", "шт", "20", "ЕЛ", 0.28, "brand",
     [("Смартфон", 9000, 28000), ("Ноутбук", 18000, 55000), ("Планшет", 7000, 20000),
      ("Навушники бездротові", 900, 6000), ("Монітор", 4500, 14000), ("Клавіатура", 600, 3500),
      ("Миша комп'ютерна", 250, 2000), ("Маршрутизатор Wi-Fi", 800, 4500), ("Зарядний пристрій", 250, 1500),
      ("Портативний акумулятор", 600, 2500), ("USB-накопичувач", 200, 1200), ("Веб-камера", 700, 3500),
      ("Принтер лазерний", 4500, 12000), ("Розумний годинник", 2000, 9000)]),
    ("home", "Побутова техніка", "Товар", "шт", "20", "ПТ", 0.22, "brand",
     [("Чайник електричний", 800, 2500), ("Блендер", 900, 4000), ("Пилосос", 2500, 14000),
      ("Мікрохвильова піч", 3000, 8000), ("Праска", 700, 3000), ("Фен", 500, 2500), ("Тостер", 600, 2000),
      ("Кавоварка", 2000, 18000), ("Мультиварка", 2000, 6500), ("Вентилятор", 700, 3500),
      ("Обігрівач", 1000, 4500), ("Міксер", 700, 3500), ("Відпарювач", 1200, 4000)]),
    ("off", "Канцтовари", "Товар", "шт", "20", "КЦ", 0.22, "size",
     [("Папір офісний (500 арк.)", 180, 300), ("Ручка кулькова", 8, 40), ("Олівець", 5, 25), ("Зошит", 12, 60),
      ("Степлер", 60, 300), ("Скотч", 15, 80), ("Маркер", 20, 90), ("Папка-реєстратор", 50, 180),
      ("Блокнот", 30, 150), ("Клей", 15, 70), ("Ножиці", 40, 200), ("Калькулятор", 150, 900),
      ("Файли прозорі (100 шт.)", 40, 140), ("Лоток для паперів", 100, 400)]),
    ("med", "Медичні вироби", "Товар", "шт", "7", "МД", 0.07, "brand",
     [("Термометр електронний", 150, 600), ("Тонометр", 800, 2500), ("Маска медична (50 шт.)", 80, 200),
      ("Пульсоксиметр", 700, 2000), ("Інгалятор", 1200, 3500), ("Бинт стерильний", 20, 80)]),
    ("exp", "Товари на експорт", "Товар", "шт", "0", "ЕК", 0.05, "size",
     [("Сувенір «Тризуб»", 80, 400), ("Вишиванка", 600, 3500), ("Мед натуральний (1 кг)", 150, 450),
      ("Крафтовий набір", 300, 1500), ("Дерев'яна іграшка", 120, 800)]),
    ("own", "Власна продукція", "Продукція", "компл", "20", "ВП", 0.08, "own",
     [("Подарунковий набір «Київ»", 450, 2500), ("Подарунковий кошик «Карпати»", 600, 2800),
      ("Сувенірний набір «Дніпро»", 300, 1800), ("Офісний набір «Старт»", 350, 1500)]),
]
# services: key, name, price from, price to, uom, role
SERVICES = [
    ("deliv", "Доставка по Україні", 150, 600, "послуга", "sold"),
    ("mount", "Монтаж та налаштування", 400, 1500, "послуга", "sold"),
    ("consult", "Консультація", 600, 1200, "год", "sold"),
    ("warr", "Гарантійне обслуговування", 500, 2500, "послуга", "sold"),
    ("train", "Навчання персоналу", 1500, 4000, "год", "sold"),
    ("rent", "Оренда офісного приміщення", 38000, 45000, "послуга", "bought"),
    ("telecom", "Послуги зв'язку та інтернету", 1100, 1500, "послуга", "bought"),
    ("ads", "Рекламні послуги", 6000, 18000, "послуга", "bought"),
    ("transp", "Транспортні послуги", 2000, 9000, "послуга", "bought"),
]
SERVICE_EXPENSE = {"rent": "Оренда приміщення", "telecom": "Зв'язок та інтернет", "ads": "Реклама та маркетинг",
                   "transp": "Транспортні витрати"}


# ------------------------------------------------------------------ public API


def make_demo(scale="small", seed=42, reset=False, delete_only=False, **overrides):
    """Create the demo data. Refuses to run when demo data exists, unless `reset`.

    reset=True deletes the demo records first, then creates them again.
    delete_only=True only deletes. `overrides` change a value of the scale
    (items, counterparties, months, docs_per_day, opening_stock_items, fast_items).
    """
    if scale not in SCALES:
        frappe.throw(f"Unknown scale {scale}. Use: {', '.join(SCALES)}")
    if frappe.session.user in (None, "Guest"):
        frappe.set_user("Administrator")
    cfg = {**SCALES[scale], **{k: v for k, v in overrides.items() if v is not None}}

    if demo_exists():
        if not (reset or delete_only):
            frappe.throw("Demo data already exists. Use --reset to delete it and create it again.")
    if reset or delete_only:
        counts = delete_demo()
        print(f"Deleted demo records: {counts}")
        if delete_only:
            return counts

    gen = Generator(cfg, int(seed))
    try:
        gen.run()
    except Exception:
        frappe.db.rollback()
        gen.flush_tags()
        frappe.db.commit()
        raise
    result = gen.summary()
    print_summary(result)
    return result


def demo_exists():
    return bool(frappe.db.exists("UA Organization", {"_user_tags": ("like", f"%{TAG}%")}))


def tagged(doctype):
    return frappe.get_all(
        doctype,
        filters={"_user_tags": ("like", f"%{TAG}%")},
        pluck="name",
        order_by="creation desc",
        limit_page_length=0,
    )


def delete_demo():
    """Cancel and delete the tagged documents, then the tagged catalogs."""
    # delete_doc queues one background job per record to clean links; run them at once instead
    original_enqueue = frappe.enqueue

    def enqueue_now(method, *args, **kwargs):
        if method == "frappe.model.delete_doc.delete_dynamic_links":
            return frappe.get_attr(method)(kwargs["doctype"], kwargs["name"])
        return original_enqueue(method, *args, **kwargs)

    frappe.enqueue = enqueue_now
    try:
        return _delete_demo()
    finally:
        frappe.enqueue = original_enqueue


def _delete_demo():
    counts = {}
    for doctype in DOC_ORDER:
        names = tagged(doctype)
        for i, name in enumerate(names, start=1):
            doc = frappe.get_doc(doctype, name)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                doc.cancel()
            if i % 50 == 0:
                frappe.db.commit()
        for name in names:
            frappe.delete_doc(doctype, name, force=1, ignore_permissions=True, delete_permanently=True)
        counts[doctype] = len(names)
        frappe.db.commit()

    for name in tagged("UA Counterparty"):
        frappe.db.set_value("UA Counterparty", name, "main_contract", None, update_modified=False)
    for doctype, is_tree in CATALOG_ORDER:
        if is_tree:
            names = frappe.get_all(
                doctype,
                filters={"_user_tags": ("like", f"%{TAG}%")},
                pluck="name",
                order_by="lft desc",
                limit_page_length=0,
            )
        else:
            names = tagged(doctype)
        for i, name in enumerate(names, start=1):
            frappe.delete_doc(doctype, name, force=1, ignore_permissions=True, delete_permanently=True)
            if i % 200 == 0:
                frappe.db.commit()
        counts[doctype] = len(names)
        frappe.db.commit()
    return {k: v for k, v in counts.items() if v}


def check_osv():
    """OSV of the demo period for the demo organization: totals and the key accounts."""
    org = frappe.db.get_value("UA Organization", {"_user_tags": ("like", f"%{TAG}%")})
    if not org:
        frappe.throw("No demo data")
    first, last = frappe.db.sql(
        "select min(posting_date), max(posting_date) from `tabUA Accounting Entry` where organization = %s", org
    )[0]
    from ua_accounting.reporting.osv import build

    table = build({"date_from": str(first), "date_to": str(last), "organizations": [org], "by_subaccounts": 1})
    total = next(r for r in table["rows"] if r["kind"] == "total")["cells"]
    accounts = {}
    for row in table["rows"]:
        code = str(row["cells"].get("label", "")).split(" ")[0]
        if code:
            accounts[code] = row["cells"]
    result = {
        "date_from": str(first),
        "date_to": str(last),
        "turn_dr": total["turn_dr"],
        "turn_cr": total["turn_cr"],
        "close_dr": total["close_dr"],
        "close_cr": total["close_cr"],
        "balanced": abs(total["turn_dr"] - total["turn_cr"]) < 0.01 and abs(total["close_dr"] - total["close_cr"]) < 0.01,
        "accounts": {
            code: {"turn_dr": accounts[code].get("turn_dr"), "turn_cr": accounts[code].get("turn_cr")}
            for code in ("281", "361", "631", "641", "644", "701", "902")
            if code in accounts
        },
    }
    return result


def print_summary(result):
    print("Created documents (submitted / draft):")
    for doctype, c in result["documents"].items():
        print(f"  {doctype}: {c['submitted']} / {c['draft']}")
    print(f"  Total: {result['documents_total']}")
    print("Catalogs:", result["catalogs"])
    osv = result["osv"]
    print(f"OSV {osv['date_from']} .. {osv['date_to']}: turnover Dt {osv['turn_dr']} Kt {osv['turn_cr']}, "
          f"closing Dt {osv['close_dr']} Kt {osv['close_cr']}, balanced: {osv['balanced']}")
    for code, v in osv["accounts"].items():
        print(f"  {code}: Dt {v['turn_dr']} Kt {v['turn_cr']}")


# ------------------------------------------------------------------ generator


def digits(rng, n):
    return str(rng.randint(1, 9)) + "".join(str(rng.randint(0, 9)) for _i in range(n - 1))


def make_iban(mfo, number):
    """UA IBAN: 2 check digits + MFO (6) + account (19)."""
    body = f"{mfo}{number:019d}"
    check = 98 - int(body + "301000") % 97  # "UA00" as digits: U=30, A=10
    return f"UA{check:02d}{body}"


class Generator:
    def __init__(self, cfg, seed):
        self.cfg = cfg
        self.rng = random.Random(seed)
        self.created = {}  # doctype -> names waiting for the tag
        self.counts = {}  # doctype -> [submitted, draft]
        self.catalog_counts = {}
        self.queue = {}  # date -> [functions]
        self.since_commit = 0

        self.end = getdate(today())
        self.start = get_first_day(add_months(self.end, -(int(cfg["months"]) - 1)))

        self.org = None
        self.persons = {}
        self.depts = {}
        self.warehouses = []  # dict(name, weight)
        self.cash_flow = {}
        self.expense = {}
        self.cash_desk = None
        self.bank_accounts = {}  # key -> name
        self.bank_balance = {}  # key -> balance (own currency)
        self.cash_balance = 0.0
        self.items = {"goods": [], "own": [], "sold_services": [], "bought_services": []}
        self.suppliers = []
        self.customers = []
        self.others = []
        self.rates = {}  # currency -> {date: rate}
        self.stock = {}  # (item name, warehouse) -> quantity
        self.account_types = {}

    # ---------------------------------------------------------------- helpers

    def run(self):
        self.currency_rates()
        self.catalogs()
        self.opening_balances()
        self.simulate()
        self.drafts()
        self.flush_tags()
        frappe.db.commit()

    def add(self, doctype, **values):
        doc = frappe.get_doc({"doctype": doctype, **values})
        doc.flags.ignore_permissions = True
        doc.insert()
        self.created.setdefault(doctype, []).append(doc.name)
        return doc

    def post(self, doctype, submit=True, **values):
        doc = self.add(doctype, **values)
        if submit:
            doc.submit()
        self.counts.setdefault(doctype, [0, 0])[0 if submit else 1] += 1
        self.since_commit += 1
        if self.since_commit >= 40:
            self.flush_tags()
            frappe.db.commit()
            self.since_commit = 0
        return doc

    def flush_tags(self):
        for doctype, names in self.created.items():
            for i in range(0, len(names), 500):
                chunk = names[i : i + 500]
                frappe.db.sql(
                    f"update `tab{doctype}` set `_user_tags` = %s where name in ({', '.join(['%s'] * len(chunk))})",
                    [f",{TAG}", *chunk],
                )
        self.created = {}

    def later(self, date, fn):
        """Run `fn` on a business day on or after `date`."""
        date = self.bday(date)
        if date <= self.end:
            self.queue.setdefault(date, []).append(fn)

    def chance(self, p):
        return self.rng.random() < p

    def count_for(self, rate):
        n = int(rate)
        return n + (1 if self.rng.random() < rate - n else 0)

    def rate_on(self, currency, date):
        if currency == "UAH":
            return 1.0
        table = self.rates[currency]
        d = date
        while d not in table:
            d -= datetime.timedelta(days=1)
        return table[d]

    # ---------------------------------------------------------------- rates

    def currency_rates(self):
        base = {"USD": 41.2, "EUR": 48.1}
        day0 = self.start - datetime.timedelta(days=7)
        for code, value in base.items():
            cur = frappe.get_doc("UA Currency", code)
            known = {getdate(r.date): flt(r.rate) / (r.multiplicity or 1) for r in cur.rates}
            table = {}
            d = day0
            while d <= self.end:
                if d.weekday() < 5:
                    value = round(value * (1 + self.rng.uniform(-0.004, 0.004)), 4)
                    if d in known:
                        table[d] = known[d]
                    else:
                        table[d] = value
                        cur.append("rates", {"date": d, "rate": value, "multiplicity": 1})
                d += datetime.timedelta(days=1)
            if len(cur.rates) != len(known):
                cur.flags.ignore_permissions = True
                cur.save()
            self.rates[code] = table
        frappe.db.commit()

    # ---------------------------------------------------------------- catalogs

    def catalogs(self):
        self.create_organization()
        self.create_structure()
        self.create_counterparties()
        self.create_items()
        self.create_assets()
        self.flush_tags()
        frappe.db.commit()

    def create_organization(self):
        rng = self.rng
        for key, name in PERSONS.items():
            self.persons[key] = self.add(
                "UA Person",
                full_name=name,
                ipn=digits(rng, 10),
                birth_date=datetime.date(rng.randint(1970, 1992), rng.randint(1, 12), rng.randint(1, 28)),
                phone=f"+38050{digits(rng, 7)}",
            ).name
        self.org = self.add(
            "UA Organization",
            org_name=ORG_NAME,
            full_name="Товариство з обмеженою відповідальністю «Демо Трейд»",
            edrpou=digits(rng, 8),
            ipn=digits(rng, 12),
            vat_payer=1,
            vat_certificate_no=digits(rng, 10),
            tax_system="Загальна система",
            default_currency="UAH",
            legal_address="01001, м. Київ, вул. Хрещатик, 22, оф. 15",
            actual_address="01001, м. Київ, вул. Хрещатик, 22, оф. 15",
            phone="+380442001122",
            email="office@demo-trade.example",
            director=self.persons["director"],
            chief_accountant=self.persons["accountant"],
            doc_prefix="ДТ",
        ).name

    def create_structure(self):
        for name, parent in DEPARTMENTS:
            self.depts[name] = self.add(
                "UA Department",
                department_name=name,
                organization=self.org,
                parent_ua_department=self.depts.get(parent) if parent else None,
                is_group=1 if any(p == name for _n, p in DEPARTMENTS) else 0,
            ).name
        for name, kind, dept, keeper, weight in WAREHOUSES:
            doc = self.add(
                "UA Warehouse",
                warehouse_name=name,
                organization=self.org,
                department=self.depts[dept],
                kind=kind,
                responsible=self.persons[keeper],
            )
            self.warehouses.append({"name": doc.name, "weight": weight, "kind": kind})
        for name, parent in CASH_FLOW_ITEMS:
            self.cash_flow[name] = self.add(
                "UA Cash Flow Item",
                item_name=name,
                parent_ua_cash_flow_item=self.cash_flow.get(parent) if parent else None,
                is_group=1 if any(p == name for _n, p in CASH_FLOW_ITEMS) else 0,
            ).name
        for name, kind in EXPENSE_ITEMS:
            self.expense[name] = self.add("UA Expense Item", item_name=name, expense_kind=kind).name

        self.cash_desk = self.add(
            "UA Cash Desk",
            cash_desk_name="Каса основна",
            organization=self.org,
            currency="UAH",
            cashier=self.persons["cashier"],
        ).name
        banks = {}
        for mfo, name, edrpou, city in BANKS:
            if frappe.db.exists("UA Bank", mfo):
                banks[mfo] = mfo
            else:
                banks[mfo] = self.add("UA Bank", bank_name=name, mfo=mfo, edrpou=edrpou, city=city).name
        specs = [
            ("uah1", "Основний рахунок UAH (ПриватБанк)", "305299", "UAH", 1),
            ("uah2", "Рахунок UAH (Ощадбанк)", "300465", "UAH", 0),
            ("usd", "Валютний рахунок USD (ПУМБ)", "334851", "USD", 0),
            ("eur", "Валютний рахунок EUR (Universal Bank)", "322001", "EUR", 0),
        ]
        for n, (key, title, mfo, cur, default) in enumerate(specs, start=1):
            self.bank_accounts[key] = self.add(
                "UA Bank Account",
                account_name=title,
                organization=self.org,
                iban=make_iban(mfo, self.rng.randint(10**12, 10**13 - 1)),
                bank=banks[mfo],
                currency=cur,
                is_default=default,
            ).name
            self.bank_balance[key] = 0.0

    def create_counterparties(self):
        rng = self.rng
        folders = {}
        for role, title in (("customer", "Покупці"), ("supplier", "Постачальники"), ("other", "Інші")):
            folders[role] = self.add("UA Counterparty", counterparty_name=title, is_group=1).name
        spec = list(COUNTERPARTIES)
        wanted = int(self.cfg["counterparties"])
        n = 0
        while len(spec) < wanted:
            n += 1
            role = "supplier" if n % 5 in (1, 2) else "customer"
            title = f"ТОВ «{rng.choice(EXTRA_WORDS_A)} {rng.choice(EXTRA_WORDS_B)} {n}»"
            spec.append((title, role, "Юридична особа", "goods" if role == "supplier" else ""))
        spec = spec[:wanted]

        for index, (title, role, kind, extra) in enumerate(spec, start=1):
            foreign = extra.startswith("foreign:") or extra.startswith("export:")
            currency = extra.split(":")[1] if foreign else "UAH"
            vat_payer = 1 if not foreign and kind != "ФОП" and self.chance(0.88) else 0
            city = rng.choice(CITIES)
            cp = self.add(
                "UA Counterparty",
                counterparty_name=title,
                full_name=title,
                parent_ua_counterparty=folders[role],
                kind=kind,
                edrpou="" if foreign else (digits(rng, 10) if kind == "ФОП" else digits(rng, 8)),
                ipn=digits(rng, 12) if vat_payer else "",
                vat_payer=vat_payer,
                is_customer=1 if role in ("customer", "other") else 0,
                is_supplier=1 if role in ("supplier", "other") else 0,
                country="Польща" if extra == "foreign:USD" else ("Німеччина" if foreign else "Україна"),
                legal_address="" if foreign else f"{rng.randint(10, 99)}000, м. {city}, {rng.choice(STREETS)}, {rng.randint(1, 120)}",
                phone=f"+38044{digits(rng, 7)}",
                email=f"office{index}@example.com",
            )
            kind_contract = {"supplier": "З постачальником", "customer": "З покупцем", "other": "Інше"}[role]
            sign_date = self.start - datetime.timedelta(days=rng.randint(60, 700))
            contract = self.add(
                "UA Counterparty Contract",
                counterparty=cp.name,
                organization=self.org,
                contract_kind=kind_contract,
                contract_title=f"Договір №{index:03d}/{sign_date.year} від {sign_date.strftime('%d.%m.%Y')}",
                contract_no=f"{index:03d}/{sign_date.year}",
                contract_date=sign_date,
                valid_to=datetime.date(self.end.year + 1, 12, 31),
                currency=currency,
                settlements_in_currency=1 if currency != "UAH" else 0,
            )
            frappe.db.set_value("UA Counterparty", cp.name, "main_contract", contract.name, update_modified=False)
            entry = {"name": cp.name, "contract": contract.name, "currency": currency, "extra": extra}
            if role == "supplier":
                self.suppliers.append(entry)
            elif role == "customer":
                self.customers.append(entry)
            else:
                self.others.append(entry)
        self.catalog_counts["UA Counterparty"] = len(spec)
        self.catalog_counts["UA Counterparty Contract"] = len(spec)

    def create_items(self):
        rng = self.rng
        total = int(self.cfg["items"])
        n_services = len(SERVICES)
        goods_total = max(total - n_services, 1)
        used = set()
        counter = 0
        for key, folder, itype, uom, vat, prefix, share, variant_kind, templates in ITEM_GROUPS:
            folder_doc = self.add("UA Item", item_name=folder, is_group=1, item_type=itype)
            count = max(1, round(goods_total * share))
            if key == ITEM_GROUPS[-1][0]:
                count = max(1, goods_total - counter)
            counter += count
            for k in range(count):
                base, low, high = templates[k % len(templates)]
                round_no = k // len(templates)
                if variant_kind == "brand":
                    variant = f"{BRANDS[(round_no + k) % len(BRANDS)]} {MODELS[(round_no * 5 + k) % len(MODELS)]}"
                elif variant_kind == "size":
                    variant = SIZES[(round_no + k) % len(SIZES)]
                else:
                    variant = OWN_VARIANTS[(round_no + k) % len(OWN_VARIANTS)]
                title = f"{base} {variant}"
                if title in used:
                    title = f"{title} №{k + 1}"
                used.add(title)
                buy = round(rng.uniform(low, high), 0 if high > 200 else 2)
                sell = round(buy * rng.uniform(1.15, 1.4), 0 if buy > 200 else 2)
                values = {
                    "item_name": title,
                    "full_name": title,
                    "parent_ua_item": folder_doc.name,
                    "item_type": itype,
                    "uom": uom,
                    "vat_rate": vat,
                    "article": f"{prefix}-{len(used):05d}",
                }
                doc = self.add_item(values)
                info = {"name": doc, "title": title, "buy": buy, "sell": sell, "vat": vat, "own": key == "own"}
                self.items["own" if key == "own" else "goods"].append(info)
        folder_doc = self.add("UA Item", item_name="Послуги", is_group=1, item_type="Послуга")
        for key, title, low, high, uom, role in SERVICES:
            name = self.add_item(
                {
                    "item_name": title,
                    "full_name": title,
                    "parent_ua_item": folder_doc.name,
                    "item_type": "Послуга",
                    "uom": uom,
                    "vat_rate": "20",
                    "article": f"ПС-{key}",
                }
            )
            price = round(rng.uniform(low, high), 0)
            self.items["sold_services" if role == "sold" else "bought_services"].append(
                {"key": key, "name": name, "title": title, "price": price, "low": low, "high": high, "vat": "20"}
            )
        if self.cfg.get("fast_items"):
            from frappe.utils.nestedset import rebuild_tree

            rebuild_tree("UA Item")
        self.catalog_counts["UA Item"] = len(used) + len(SERVICES)

    def add_item(self, values):
        """Insert a UA Item and return its name. Big loads skip the tree update and rebuild it once."""
        if not self.cfg.get("fast_items"):
            return self.add("UA Item", **values).name
        doc = frappe.get_doc({"doctype": "UA Item", **values})
        doc.flags.ignore_permissions = True
        doc.set_user_and_timestamp()
        doc._set_defaults()
        doc.set_new_name()
        doc.db_insert()
        self.created.setdefault("UA Item", []).append(doc.name)
        if len(self.created["UA Item"]) >= 2000:
            self.flush_tags()
            frappe.db.commit()
        return doc.name

    def create_assets(self):
        a = self.add
        resp = self.persons["accountant"]
        self.assets = {"fixed": [], "intangible": [], "low": []}
        fixed = [
            ("Сервер стійковий Veltra R240", "4. Машини та обладнання", "104", 168000, "Адміністрація", 60),
            ("Автомобіль вантажний Nova Transit", "5. Транспортні засоби", "105", 1150000, "Склад", 96),
            ("Меблі офісні (комплект)", "6. Інструменти, прилади, інвентар (меблі)", "106", 185000, "Адміністрація", 96),
            ("Стелажі складські", "6. Інструменти, прилади, інвентар (меблі)", "106", 96000, "Склад", 120),
        ]
        for n, (title, group, account, cost, dept, life) in enumerate(fixed, start=1):
            doc = a("UA Fixed Asset", asset_name=title, inventory_no=f"ОЗ-{n:04d}", organization=self.org,
                    asset_group=group, department=self.depts[dept], responsible=self.persons["keeper1"],
                    commissioning_date=self.start - datetime.timedelta(days=self.rng.randint(200, 900)),
                    useful_life_months=life, depreciation_method="Прямолінійний")
            self.assets["fixed"].append((doc.name, account, cost))
        intangible = [
            ("Програмне забезпечення «Облік складу»", "5. Авторське право та суміжні з ним права", "125", 120000),
            ("Право на торговельну марку «Демо Трейд»", "3. Права на комерційні позначення", "123", 45000),
        ]
        for n, (title, kind, account, cost) in enumerate(intangible, start=1):
            doc = a("UA Intangible Asset", asset_name=title, inventory_no=f"НМА-{n:04d}", organization=self.org,
                    asset_kind=kind, useful_life_months=60,
                    commissioning_date=self.start - datetime.timedelta(days=self.rng.randint(200, 700)))
            self.assets["intangible"].append((doc.name, account, cost))
        low = [("Принтер багатофункціональний", 8400), ("Холодильник офісний", 9600), ("Кавомашина", 14500)]
        for n, (title, cost) in enumerate(low, start=1):
            doc = a("UA Low Value Asset", asset_name=title, inventory_no=f"МНМА-{n:04d}", uom="шт",
                    organization=self.org, responsible=resp)
            self.assets["low"].append((doc.name, "112", cost))
        self.catalog_counts["UA Fixed Asset"] = len(fixed)
        self.catalog_counts["UA Intangible Asset"] = len(intangible)
        self.catalog_counts["UA Low Value Asset"] = len(low)

    # ---------------------------------------------------------------- opening balances

    def row(self, dr, cr, amount, dr_sub=(), cr_sub=(), **extra):
        values = {"account_dr": dr, "account_cr": cr, "amount": flt(amount, 2)}
        for side, account, sub in (("dr", dr, dr_sub), ("cr", cr, cr_sub)):
            types = self.subconto_doctypes(account)
            for i, value in enumerate(sub, start=1):
                values[f"subconto_{side}{i}"] = value
                values[f"subconto_{side}{i}_type"] = types[i - 1]
        values.update(extra)
        return values

    def subconto_doctypes(self, account):
        """DocType of every subconto slot of an account (the form needs it for dynamic links)."""
        if account not in self.account_types:
            self.account_types[account] = frappe.db.sql_list(
                """select t.reference_doctype from `tabUA Account Subconto` s
                left join `tabUA Subconto Type` t on t.name = s.subconto_type
                where s.parent = %s and s.parenttype = 'UA Account' order by s.idx""",
                account,
            )
        return self.account_types[account]

    def opening_balances(self):
        date = self.start
        usd_rate = self.rate_on("USD", date)
        cash, bank1, bank2, usd = 95000.0, 1850000.0, 420000.0, 18000.0
        self.cash_balance = cash
        self.bank_balance["uah1"], self.bank_balance["uah2"], self.bank_balance["usd"] = bank1, bank2, usd

        rows = [
            self.row("301", "401", cash, [self.cash_desk], content="Залишок готівки в касі"),
            self.row("311", "401", bank1, [self.bank_accounts["uah1"]], content="Залишок на рахунку"),
            self.row("311", "401", bank2, [self.bank_accounts["uah2"]], content="Залишок на рахунку"),
            self.row("312", "401", usd * usd_rate, [self.bank_accounts["usd"]], content="Залишок на валютному рахунку",
                     currency_dr="USD", currency_amount_dr=usd),
        ]
        for kind, assets in self.assets.items():
            for name, account, cost in assets:
                wear = {"fixed": "131", "intangible": "133", "low": "132"}[kind]
                rows.append(self.row(account, "401", cost, [name], content="Первісна вартість"))
                rows.append(self.row("401", wear, round(cost * 0.3, 2), [], [name], content="Накопичений знос"))
        self.post("UA Journal Operation", organization=self.org, posting_date=date,
                  content="Введення залишків: каса, банк, необоротні активи", entries=rows)

        # opening stock
        rows = []
        goods = self.items["goods"]
        stocked = self.rng.sample(goods, min(len(goods), int(self.cfg["opening_stock_items"])))
        for info in stocked:
            for wh in self.warehouses:
                if wh is not self.warehouses[0] and not self.chance(0.3):
                    continue
                qty = self.rng.randint(*self.qty_range(info["buy"], 1.5))
                self.stock[(info["name"], wh["name"])] = float(qty)
                rows.append(self.row("281", "401", qty * info["buy"], [info["name"], wh["name"]],
                                     content="Залишок товарів", quantity_dr=qty))
        for info in self.items["own"]:
            wh = self.warehouses[0]["name"]
            qty = self.rng.randint(5, 40)
            self.stock[(info["name"], wh)] = float(qty)
            rows.append(self.row("26", "401", qty * info["buy"], [info["name"], wh],
                                 content="Залишок готової продукції", quantity_dr=qty))
        for i in range(0, len(rows), 500):
            self.post("UA Journal Operation", organization=self.org, posting_date=date,
                      content="Введення залишків: товари та продукція", entries=rows[i : i + 500])
        self.flush_tags()
        frappe.db.commit()

    def qty_range(self, price, factor=1):
        """Quantity range by price: cheap goods are taken in bigger lots."""
        high = max(2, int(15000 * factor / max(price, 1)))
        high = min(high, 300)
        return max(1, high // 4), high

    # ---------------------------------------------------------------- simulation

    def simulate(self):
        cfg = self.cfg
        per_day = cfg["docs_per_day"]
        sales_rate = per_day * 0.6 / 3.2
        purchase_rate = per_day * 0.27 / 3.0
        self.schedule_monthly()
        d = self.start + datetime.timedelta(days=1)
        while d <= self.end:
            for fn in self.queue.pop(d, []):
                fn()
            if d.weekday() < 5:
                for _i in range(self.count_for(purchase_rate)):
                    self.purchase_chain(d)
                for _i in range(self.count_for(sales_rate)):
                    self.sales_chain(d)
            d += datetime.timedelta(days=1)
        self.flush_tags()
        frappe.db.commit()

    # ------------------------------------------------ money helpers

    def pick_account(self, amount, currency):
        """Bank account key with enough money, or None."""
        keys = {"UAH": ["uah1", "uah2"], "USD": ["usd"], "EUR": ["eur"]}[currency]
        for key in sorted(keys, key=lambda k: -self.bank_balance[k]):
            if self.bank_balance[key] >= amount:
                return key
        return None

    def money_in(self, date, cp, amount, currency, doc_link=None, advance=False, vat=None):
        """Cash receipt from a buyer. Cash desk for small UAH amounts, otherwise bank."""
        amount = flt(amount, 2)
        if amount <= 0:
            return None
        values = {
            "organization": self.org,
            "posting_date": date,
            "operation_type": "Оплата від покупця",
            "counterparty": cp["name"],
            "contract": cp["contract"],
            "amount": amount,
            "currency": currency,
            "cash_flow_item": self.cash_flow["Оплата від покупців"],
            "settlement_type": "Передоплата (аванс)" if advance else "Оплата за реалізацію",
        }
        if advance:
            values["vat_rate"] = vat or "20"
        if doc_link:
            values["sales_invoice"] = doc_link
        if currency == "UAH" and amount <= 20000 and self.chance(0.2):
            values.update(cash_type="Каса", cash_desk=self.cash_desk)
            self.cash_balance += amount
        else:
            key = {"UAH": self.rng.choice(["uah1", "uah1", "uah2"]), "USD": "usd", "EUR": "eur"}[currency]
            values.update(cash_type="Банк", bank_account=self.bank_accounts[key])
            self.bank_balance[key] += amount
        return self.post("UA Cash Receipt", **values)

    def money_out(self, date, cp, amount, currency, doc_link=None, advance=False, vat=None, retry=3):
        """Cash payment to a supplier. Postponed when there is not enough money."""
        amount = flt(amount, 2)
        if amount <= 0:
            return None
        use_cash = currency == "UAH" and amount <= 12000 and self.cash_balance >= amount and self.chance(0.25)
        key = None if use_cash else self.pick_account(amount, currency)
        if not use_cash and key is None:
            if retry > 0:
                self.later(date + datetime.timedelta(days=4),
                           lambda: self.money_out(self.cur_day_after(date, 4), cp, amount, currency, doc_link,
                                                  advance, vat, retry - 1))
            return None
        values = {
            "organization": self.org,
            "posting_date": date,
            "operation_type": "Оплата постачальнику",
            "counterparty": cp["name"],
            "contract": cp["contract"],
            "amount": amount,
            "currency": currency,
            "cash_flow_item": self.cash_flow["Оплата постачальникам"],
            "settlement_type": "Передоплата (аванс)" if advance else "Оплата за надходження",
            "tax_invoice_received": 1,
        }
        if advance:
            values["vat_rate"] = vat or "20"
        if doc_link:
            values["purchase_receipt"] = doc_link
        if use_cash:
            values.update(cash_type="Каса", cash_desk=self.cash_desk)
            self.cash_balance -= amount
        else:
            values.update(cash_type="Банк", bank_account=self.bank_accounts[key])
            self.bank_balance[key] -= amount
        return self.post("UA Cash Payment", **values)

    def cur_day_after(self, date, days):
        return self.bday(date + datetime.timedelta(days=days))

    @staticmethod
    def bday(date):
        """The same day, or the next Monday for a weekend."""
        while date.weekday() >= 5:
            date += datetime.timedelta(days=1)
        return date

    def applied_advance(self, doc, debit, credit):
        """Amount of the offset of an advance that the document posted."""
        return flt(
            frappe.db.sql(
                "select coalesce(sum(amount), 0) from `tabUA Accounting Entry` "
                "where registrar_type = %s and registrar = %s and account_dr = %s and account_cr = %s",
                (doc.doctype, doc.name, debit, credit),
            )[0][0],
            2,
        )

    # ------------------------------------------------ purchases

    def purchase_chain(self, d):
        rng = self.rng
        foreign = [s for s in self.suppliers if s["extra"].startswith("foreign:")]
        domestic = [s for s in self.suppliers if s["extra"] in ("goods", "")]
        if foreign and self.chance(0.08):
            sup = rng.choice(foreign)
        else:
            sup = rng.choice(domestic)
        currency = sup["currency"]
        rate = self.rate_on(currency, d)
        wh = self.pick_warehouse(wholesale_only=True)
        lines = []
        for info in rng.sample(self.items["goods"], min(len(self.items["goods"]), rng.randint(2, 6))):
            price = info["buy"] * rng.uniform(0.97, 1.03)
            qty = rng.randint(*self.qty_range(info["buy"]))
            lines.append({"item": info["name"], "quantity": qty, "price": round(price / rate, 2) if currency != "UAH" else round(price, 2),
                          "vat_rate": info["vat"], "warehouse": wh})
        header = {"organization": self.org, "counterparty": sup["name"], "contract": sup["contract"],
                  "warehouse": wh, "currency": currency, "vat_mode": "ПДВ зверху"}
        order = self.post("UA Supplier Order", posting_date=d, goods=lines, **header)
        # prepayment of some orders
        if currency == "UAH" and self.chance(0.12):
            est = sum(l["quantity"] * l["price"] * (1 + float(l["vat_rate"]) / 100) for l in lines)
            self.money_out(d, sup, est * rng.uniform(0.3, 0.6), "UAH", advance=True)
        if self.chance(0.1):
            return  # the order stays open
        receipt_day = self.cur_day_after(d, rng.randint(1, 4))
        if receipt_day > self.end:
            return
        self.later(receipt_day, lambda: self.purchase_receipt(receipt_day, sup, header, lines, order.name))

    def purchase_receipt(self, d, sup, header, lines, order_name):
        rng = self.rng
        currency = sup["currency"]
        doc = self.post("UA Purchase Receipt", posting_date=d, goods=lines, supplier_order=order_name,
                        tax_invoice_received=0 if self.chance(0.08) else 1, offset_prepayment=1, **header)
        for l in lines:
            key = (l["item"], l["warehouse"])
            self.stock[key] = self.stock.get(key, 0.0) + l["quantity"]
        self.pay_supplier_later(d, sup, doc, currency, self.applied_advance(doc, "631", "371"))

    def pay_supplier_later(self, d, sup, doc, currency, applied):
        due = flt(doc.total_amount - (applied if currency == "UAH" else 0), 2)
        if due <= 0 or self.chance(0.12):
            return
        if self.chance(0.1):
            due = flt(due * self.rng.uniform(0.4, 0.8), 2)
        pay_day = self.cur_day_after(d, self.rng.randint(2, 20))
        self.later(pay_day, lambda: self.money_out(pay_day, sup, due, currency, doc_link=doc.name))

    def pick_warehouse(self, wholesale_only=False):
        warehouses = [wh for wh in self.warehouses if not wholesale_only or wh["kind"] != "Роздрібний"]
        r = self.rng.random() * sum(wh["weight"] for wh in warehouses)
        acc = 0.0
        for wh in warehouses:
            acc += wh["weight"]
            if r <= acc:
                return wh["name"]
        return warehouses[0]["name"]

    # ------------------------------------------------ sales

    def sales_chain(self, d):
        rng = self.rng
        export = [c for c in self.customers if c["extra"].startswith("export:")]
        domestic = [c for c in self.customers if not c["extra"].startswith("export:")]
        cust = rng.choice(export) if export and self.chance(0.07) else rng.choice(domestic)
        currency = cust["currency"]
        rate = self.rate_on(currency, d)
        wh = self.pick_warehouse(wholesale_only=True)
        want = rng.randint(1, 4)
        lines = []
        seen = set()
        pool = self.items["goods"] + self.items["own"] * 3 if self.items["own"] else self.items["goods"]
        for _try in range(60):
            if len(lines) >= want:
                break
            info = rng.choice(pool)
            if info["name"] in seen:
                continue
            avail = self.stock.get((info["name"], wh), 0.0)
            if avail <= 0:
                continue
            seen.add(info["name"])
            qty = min(avail, rng.randint(1, max(1, int(avail * 0.5) + 1)))
            price = info["sell"] * rng.uniform(0.97, 1.03)
            lines.append({"item": info["name"], "quantity": qty,
                          "price": round(price / rate, 2) if currency != "UAH" else round(price, 2),
                          "vat_rate": "0" if currency != "UAH" else info["vat"], "warehouse": wh})
        if not lines:
            return
        header = {"organization": self.org, "counterparty": cust["name"], "contract": cust["contract"],
                  "warehouse": wh, "currency": currency, "vat_mode": "ПДВ зверху"}
        order = self.post("UA Customer Order", posting_date=d, goods=lines, **header)
        if currency == "UAH" and self.chance(0.12):
            est = sum(l["quantity"] * l["price"] * (1 + float(l["vat_rate"]) / 100) for l in lines)
            self.money_in(d, cust, est * rng.uniform(0.3, 0.7), "UAH", advance=True)
        if self.chance(0.1):
            return  # the order stays open
        invoice_day = self.cur_day_after(d, rng.randint(0, 3))
        if invoice_day > self.end:
            return
        if invoice_day == d:
            self.sales_invoice(d, cust, header, lines, order.name)
        else:
            self.later(invoice_day, lambda: self.sales_invoice(invoice_day, cust, header, lines, order.name))

    def sales_invoice(self, d, cust, header, lines, order_name):
        rng = self.rng
        currency = cust["currency"]
        rows = []
        for l in lines:
            key = (l["item"], l["warehouse"])
            qty = min(l["quantity"], self.stock.get(key, 0.0))
            if qty > 0:
                rows.append({**l, "quantity": qty})
        if not rows:
            return  # no stock left: the order stays open
        services = []
        if self.items["sold_services"] and self.chance(0.25):
            svc = rng.choice(self.items["sold_services"])
            price = round(svc["price"] * rng.uniform(0.9, 1.1), 2)
            services.append({"item": svc["name"], "quantity": 1,
                             "price": round(price / self.rate_on(currency, d), 2) if currency != "UAH" else price,
                             "vat_rate": "0" if currency != "UAH" else "20"})
        doc = self.post("UA Sales Invoice", posting_date=d, goods=rows, services=services,
                        customer_order=order_name, offset_advance=1, **header)
        for r in rows:
            key = (r["item"], r["warehouse"])
            self.stock[key] = self.stock[key] - r["quantity"]
        applied = self.applied_advance(doc, "681", "361") if currency == "UAH" else 0
        due = flt(doc.total_amount - applied, 2)
        if due <= 0 or self.chance(0.1):
            return
        if self.chance(0.1):
            due = flt(due * rng.uniform(0.4, 0.8), 2)
        pay_day = self.cur_day_after(d, rng.randint(2, 25))
        if pay_day <= self.end:
            self.later(pay_day, lambda: self.money_in(pay_day, cust, due, currency, doc_link=doc.name))

    # ------------------------------------------------ monthly documents

    def schedule_monthly(self):
        months = []
        d = self.start
        while d <= self.end:
            months.append(d)
            d = get_first_day(add_months(d, 1))
        by_key = {s["key"]: s for s in self.items["bought_services"]}
        by_role = {}
        for sup in self.suppliers:
            if sup["extra"].startswith("service:"):
                by_role[sup["extra"].split(":")[1]] = sup
        plan = [("rent", 3), ("telecom", 3), ("ads", 12), ("transp", 20)]
        for first in months:
            for key, day in plan:
                svc = by_key.get(key)
                sup = by_role.get(key) or by_role.get("rent") or (self.suppliers[0] if self.suppliers else None)
                if not svc or not sup:
                    continue
                when = first + datetime.timedelta(days=day - 1)
                when = self.bday(max(when, self.start + datetime.timedelta(days=1)))
                if key == "transp" and not self.chance(0.7):
                    continue
                self.later(when, lambda svc=svc, sup=sup, key=key, when=when: self.service_receipt(when, svc, sup, key))
            for day in (8, 24):
                when = self.bday(first + datetime.timedelta(days=day - 1))
                if when > self.start:
                    self.later(when, lambda when=when: self.small_expense(when))

    def service_receipt(self, d, svc, sup, key):
        rng = self.rng
        price = round(svc["price"] * rng.uniform(0.95, 1.05) if key != "rent" else svc["price"], 2)
        row = {"item": svc["name"], "quantity": 1, "price": price, "vat_rate": svc["vat"],
               "expense_item": self.expense[SERVICE_EXPENSE[key]],
               "department": self.depts["Адміністрація" if key != "ads" else "Відділ продажів"]}
        doc = self.post("UA Purchase Receipt", organization=self.org, posting_date=d, counterparty=sup["name"],
                        contract=sup["contract"], currency="UAH", vat_mode="ПДВ зверху", services=[row],
                        offset_prepayment=1, tax_invoice_received=1)
        self.pay_supplier_later(d, sup, doc, "UAH", 0)

    def small_expense(self, d):
        """Other expense from the cash desk: Dt 92."""
        amount = round(self.rng.uniform(500, 3000), 2)
        if self.cash_balance < amount:
            return
        self.cash_balance -= amount
        self.post("UA Cash Payment", organization=self.org, posting_date=d, operation_type="Інша витрата",
                  cash_type="Каса", cash_desk=self.cash_desk, amount=amount, currency="UAH",
                  cash_flow_item=self.cash_flow["Господарські витрати"], other_account="92",
                  expense_item=self.expense["Господарські матеріали"], department=self.depts["Адміністрація"],
                  comment="Господарські та канцелярські витрати")

    # ---------------------------------------------------------------- drafts and summary

    def drafts(self):
        """A few documents on the last days stay as drafts."""
        d = self.end
        while d.weekday() >= 5:
            d -= datetime.timedelta(days=1)
        for _i in range(2):
            cust = self.rng.choice([c for c in self.customers if c["currency"] == "UAH"])
            wh = self.warehouses[0]["name"]
            keys = [k for k, v in self.stock.items() if k[1] == wh and v > 3]
            if not keys:
                break
            item = self.rng.choice(keys)[0]
            info = next(i for i in self.items["goods"] + self.items["own"] if i["name"] == item)
            lines = [{"item": item, "quantity": 2, "price": info["sell"], "vat_rate": info["vat"], "warehouse": wh}]
            header = {"organization": self.org, "counterparty": cust["name"], "contract": cust["contract"],
                      "warehouse": wh, "currency": "UAH", "vat_mode": "ПДВ зверху"}
            self.post("UA Customer Order", submit=False, posting_date=d, goods=lines, **header)
        sup = next((s for s in self.suppliers if s["extra"] == "goods"), None)
        if sup:
            info = self.items["goods"][0]
            wh = self.warehouses[0]["name"]
            lines = [{"item": info["name"], "quantity": 5, "price": info["buy"], "vat_rate": info["vat"], "warehouse": wh}]
            self.post("UA Purchase Receipt", submit=False, organization=self.org, posting_date=d,
                      counterparty=sup["name"], contract=sup["contract"], warehouse=wh, currency="UAH",
                      vat_mode="ПДВ зверху", goods=lines)
        cust = next((c for c in self.customers if c["currency"] == "UAH"), None)
        if cust:
            self.post("UA Cash Receipt", submit=False, organization=self.org, posting_date=d,
                      operation_type="Оплата від покупця", cash_type="Банк",
                      bank_account=self.bank_accounts["uah1"], amount=12500, currency="UAH",
                      counterparty=cust["name"], contract=cust["contract"], settlement_type="Оплата за реалізацію")

    def summary(self):
        documents = {}
        for doctype, (done, draft) in self.counts.items():
            documents[doctype] = {"submitted": done, "draft": draft}
        total = sum(c["submitted"] + c["draft"] for c in documents.values())
        return {
            "organization": self.org,
            "period": [str(self.start), str(self.end)],
            "catalogs": self.catalog_counts,
            "documents": documents,
            "documents_total": total,
            "osv": check_osv(),
        }
