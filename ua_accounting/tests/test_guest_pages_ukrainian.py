"""The pages a user sees before login (sign in, forgot password, e-mail link, password reset, 404/403) are Ukrainian only."""

import json
import os
import re

import frappe
from frappe.tests import IntegrationTestCase

# files of the platform whose _("...") strings reach a Guest; every one must be translated
SOURCES = ("templates/includes/login/login.js", "www/login.html", "www/login.py", "www/404.html", "www/message.html",
           "www/update-password.html", "www/update_password.py", "www/error.html")
# the navbar, the user menu, the about dialog and the notifications of the desk
DESK_SOURCES = ("public/js/frappe/ui/toolbar/about.js", "public/js/frappe/ui/toolbar/navbar.html",
                "public/js/frappe/ui/notifications/notifications.js", "templates/includes/navbar/navbar_items.html",
                "templates/includes/navbar/navbar_login.html")
# words that stay Latin in Ukrainian text: product names, domain terms
ALLOWED = {"frappe", "framework", "hivebooks", "hivetrade", "beeone", "email", "ldap", "google", "github", "facebook",
           "office", "salesforce", "otp", "sms", "http", "https", "html", "css", "js", "id", "ok", "ip", "api", "sso",
           "jane", "example", "com", "javascript", "viewport", "utf", "width", "device", "initial", "scale", "csrf",
           "token", "ua", "uk", "en", "px", "rem", "svg", "url", "lang", "ltr", "rtl"}
# names and examples, not words
NOT_TRANSLATED = {"&copy; Frappe Technologies Pvt. Ltd. and contributors", "{0} = {1}", "beeone", "jane@example.com", "на основі Frappe Framework"}
_LITERAL = re.compile(r"""\b__?\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")


def source_strings(names=SOURCES):
	"""Translatable strings of the guest-facing templates, with the placeholders cut out."""
	found = set()
	for name in names:
		with open(os.path.join(frappe.get_app_path("frappe"), name), encoding="utf-8") as handle:
			for double, single in _LITERAL.findall(handle.read()):
				text = (double or single).replace("\\'", "'").replace('\\"', '"')
				if re.search(r"[A-Za-z]{3}", text) and text not in NOT_TRANSLATED:
					found.add(text)
	return sorted(found)


def visible_text(html):
	"""Text a user reads: no scripts, styles, comments or tags; attributes that show text are kept."""
	html = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>|<!--.*?-->", " ", html)
	shown = re.findall(r"""(?i)\b(?:placeholder|title|alt|aria-label|value)=["']([^"'{}]*)["']""", html)
	text = re.sub(r"(?s)<[^>]+>", " ", html)
	return " ".join([text, *shown])


def english_words(html):
	words = re.findall(r"[A-Za-z][A-Za-z']+", visible_text(html))
	return sorted({w for w in words if w.lower() not in ALLOWED and len(w) > 1})


class TestGuestPagesUkrainian(IntegrationTestCase):
	def request(self, method, path, **kwargs):
		"""A real request to the site as a Guest, through the WSGI application; the test connection is reopened after it."""
		from frappe.app import application
		from werkzeug.test import Client

		site = frappe.local.site
		try:
			response = Client(application).open(path, method=method, headers={"X-Frappe-Site-Name": site}, **kwargs)
			return response.status_code, response.get_data(as_text=True)
		finally:
			frappe.init(site)
			frappe.connect()

	def page(self, path, status=200):
		code, html = self.request("GET", path)
		self.assertEqual(code, status, path)
		return html

	def assert_ukrainian(self, path, status=200):
		html = self.page(path, status)
		self.assertEqual(english_words(html), [], f"English words on {path}")
		self.assertTrue(re.search("[А-Яа-яІіЇїЄє]", visible_text(html)), path)
		# a source string of the guest templates that is still in the page was not translated
		for text in source_strings():
			if len(text) > 12:
				self.assertNotIn(text, html, f"untranslated on {path}")
		return html

	def test_login_page_is_ukrainian(self):
		html = self.assert_ukrainian("/login")
		for text in ("Ласкаво просимо", "Забули пароль?", "Вхід"):
			self.assertIn(text, html)
		for text in ("Sign In", "Welcome! Please sign in to continue.", "Forgot password?", "Login with Email Link"):
			self.assertNotIn(text, html)

	def test_login_script_messages_are_ukrainian(self):
		html = self.page("/login")
		for text in ("Invalid credentials, try again.", "Both login and password required", "Too many requests"):
			self.assertNotIn(text, html)
		# the script writes its strings as JSON, with \uXXXX escapes
		self.assertIn(json.dumps("Неправильний логін або пароль, спробуйте ще раз.").lower(), html.lower())

	def test_every_guest_template_string_is_translated(self):
		from frappe.translate import get_all_translations

		translations = get_all_translations("uk")
		self.assertEqual([s for s in source_strings() if not translations.get(s)], [])

	def test_desk_navbar_user_menu_and_notifications_are_translated(self):
		from frappe.translate import get_all_translations

		translations = get_all_translations("uk")
		self.assertEqual([s for s in source_strings(DESK_SOURCES) if not translations.get(s)], [])

	def test_not_found_page_is_ukrainian(self):
		self.assert_ukrainian("/no-such-page-691", 404)

	def test_not_permitted_page_is_ukrainian(self):
		code, html = self.request("GET", "/printview?doctype=User&name=Administrator")
		self.assertIn(code, (403, 401, 302))
		if code == 403:
			self.assertEqual(english_words(html), [])

	def test_password_reset_page_is_ukrainian(self):
		html = self.page("/update-password")
		self.assertEqual(english_words(html), [])

