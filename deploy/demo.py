"""First-start demo seed; imported by bench execute, never by the application."""
import os
import frappe


def run():
    app = os.environ['CONFIGURATION_APP']
    marker = f'{app}_deployment_demo_v1'
    if frappe.conf.get(marker):
        print('Demo data already initialized; leaving records unchanged.')
        return
    frappe.set_user('Administrator')
    if app == 'ua_accounting':
        from ua_accounting.setup.demo import make_demo, demo_exists
        if demo_exists():
            raise RuntimeError('Partial/existing accounting demo detected. Inspect data before marking demo complete; automatic reset is disabled.')
        make_demo(scale='small', items=30, counterparties=30, months=1, docs_per_day=1, opening_stock_items=20)
    elif app == 'ua_trade':
        seed_trade()
    else:
        raise ValueError(app)
    frappe.db.set_single_value('System Settings', 'language', 'uk')
    frappe.db.set_value('User', 'Administrator', 'language', 'uk')
    frappe.db.commit()
    from frappe.installer import update_site_config
    update_site_config(marker, True)
    print('Demo data initialized.')


def seed_trade():
    """Small catalog demo, all inserts use normal document validation."""
    def ensure(doctype, field, value, **values):
        existing = frappe.db.get_value(doctype, {field: value}, 'name')
        if existing:
            return existing
        return frappe.get_doc({'doctype': doctype, field: value, **values}).insert(ignore_permissions=True).name

    org = ensure('UT Organization', 'org_name', 'Демо Торгівля', full_name='ТОВ «Демо Торгівля»', edrpou='12345678', doc_prefix='ДЕМО')
    ensure('UT Warehouse', 'warehouse_name', 'Демо: основний склад', organization=org, warehouse_kind='Оптовий')
    kind = ensure('UT Item Kind', 'kind_name', 'Демо: товари', item_type='Товар', default_uom='шт', default_vat_rate='20%')
    for index, title in enumerate(('Ноутбук', 'Монітор', 'Клавіатура', 'Миша', 'Кабель USB'), 1):
        ensure('UT Item', 'article', f'DEMO-{index:03}', item_name=f'Демо: {title}', item_kind=kind, uom='шт', vat_rate='20%')
    for title, customer, supplier in (('Демо: покупець', 1, 0), ('Демо: постачальник', 0, 1)):
        partner = ensure('UT Partner', 'partner_name', title, is_customer=customer, is_supplier=supplier)
        ensure('UT Counterparty', 'counterparty_name', title, full_name=title, partner=partner, legal_form='Фізична особа')
    ensure('UT Price Type', 'price_type_name', 'Демо: роздрібна', price_kind='Продаж', currency='UAH', price_includes_vat=1)
