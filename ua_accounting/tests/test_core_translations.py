"""Every string of the core shell, setup and demo code has a Ukrainian translation in this app (single-language site)."""

from frappe.beeone.setup import missing_translations
from frappe.tests import IntegrationTestCase


class TestCoreTranslations(IntegrationTestCase):
	def test_core_strings_are_translated_to_ukrainian(self):
		self.assertEqual(missing_translations("uk"), [])
