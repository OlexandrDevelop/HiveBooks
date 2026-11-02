# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Tests for QR code and amount in words in accounting print formats."""

import unittest

from ua_accounting.accounting.utils import money_in_words
from ua_accounting.setup import print_formats


class TestAccountingPrintQR(unittest.TestCase):
	"""Test print format definitions for QR macro and amount in words."""

	def test_macros_contain_qr_definition(self):
		"""MACROS defines the qr(payload) macro using qr_code helper."""
		self.assertIn("{% macro qr(payload) %}", print_formats.MACROS)
		self.assertIn("{{ qr_code(payload) }}", print_formats.MACROS)

	def test_sales_invoice_contains_qr_and_words(self):
		"""SALES_INVOICE template embeds qr macro and money_in_words."""
		self.assertIn("{{ qr(", print_formats.SALES_INVOICE)
		self.assertIn("money_in_words(", print_formats.SALES_INVOICE)

	def test_payment_invoice_contains_qr_and_words(self):
		"""INVOICE template embeds qr macro and money_in_words."""
		self.assertIn("{{ qr(", print_formats.INVOICE)
		self.assertIn("money_in_words(", print_formats.INVOICE)

	def test_money_in_words_ukrainian_formatting(self):
		"""money_in_words formats hryvnias and kopecks correctly in Ukrainian."""
		res = money_in_words(1234.56, "UAH")
		self.assertIn("Одна тисяча двісті тридцять чотири гривні 56 копійок", res)

	def test_style_contains_qr_styling(self):
		"""STYLE defines .qr class with appropriate image dimensions."""
		self.assertIn(".ua-form .qr", print_formats.STYLE)


if __name__ == "__main__":
	unittest.main()
