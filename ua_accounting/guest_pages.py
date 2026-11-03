"""Pages of the website part (login, 404, password reset): the platform sets some page titles untranslated."""

import frappe

TITLE_TAGS = ("title", "og:title", "twitter:title")


def translate_title(context):
	"""`update_website_context` hook: the title of the page and of its meta tags in the language of the user."""
	title = context.get("title")
	if not title or not isinstance(title, str):
		return
	translated = frappe._(title)
	if translated == title:
		return
	context.title = translated
	tags = context.get("metatags")
	if isinstance(tags, dict):
		for name in TITLE_TAGS:
			if tags.get(name) == title:
				tags[name] = translated
