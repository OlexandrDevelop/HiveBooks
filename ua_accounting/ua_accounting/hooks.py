app_name = "ua_accounting"
app_title = "Бухгалтерія UA"
app_publisher = "UA Accounting"
app_description = "Accounting system for Ukraine (chart of accounts No. 291, subconto, ledger)"
app_email = "olexandr.develop@gmail.com"
app_license = "MIT"

# the app depends only on frappe
required_apps = []

add_to_apps_screen = [
    {
        "name": "ua_accounting",
        "logo": "/assets/ua_accounting/images/logo.svg",
        "title": "Бухгалтерія",
        "route": "/app/бухгалтерія",
    }
]

app_include_css = "/assets/ua_accounting/css/ua_desk.css"
app_include_js = [
    "/assets/ua_accounting/js/ua_desk.js",
    "/assets/ua_accounting/js/ua_tree_sidebar.js",
]

before_install = "ua_accounting.install.before_install"
after_install = "ua_accounting.install.after_install"
before_migrate = "ua_accounting.install.before_migrate"
after_migrate = "ua_accounting.install.after_migrate"
