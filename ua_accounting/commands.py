"""Bench commands of the app. Frappe finds the `commands` list by itself."""

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("ua-demo")
@click.option("--scale", default="small", type=click.Choice(["small", "large"]), help="Size of the demo data")
@click.option("--seed", default=42, type=int, help="Same seed gives the same data")
@click.option("--reset", is_flag=True, help="Delete the old demo data first, then create it again")
@click.option("--delete-only", is_flag=True, help="Only delete the demo data")
@pass_context
def ua_demo(context, scale, seed, reset, delete_only):
    """Create demo data (catalogs, opening balances, posted documents)."""
    from ua_accounting.setup.demo import make_demo

    site = get_site(context)
    frappe.init(site=site)
    frappe.connect()
    try:
        frappe.set_user("Administrator")
        make_demo(scale=scale, seed=seed, reset=reset, delete_only=delete_only)
    finally:
        frappe.destroy()


commands = [ua_demo]
