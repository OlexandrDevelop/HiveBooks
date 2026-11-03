app_name = "owner_custom"
app_title = "Власні зміни"
app_publisher = "Owner"
app_description = "Власні зміни власника встановлення"
app_email = ""
app_license = "mit"

required_apps = ["ua_accounting"]

# Приклади (розкоментуйте та змініть). Докладніше: CUSTOMIZE.md

# Серверна логіка після подій документів:
# doc_events = {
#     "Sales Invoice": {"validate": "owner_custom.events.validate_invoice"},
# }

# Підміна класу документа (лише один застосунок може підміняти той самий DocType):
# override_doctype_class = {
#     "Item": "owner_custom.overrides.MyItem",
# }

# Додатковий скрипт форми для чужого DocType:
# doctype_js = {"Item": "public/js/item.js"}

# Власні поля та налаштування як fixtures (./bench.sh export-fixtures --app owner_custom):
# fixtures = [{"dt": "Custom Field", "filters": [["module", "=", "Owner Custom"]]}]
