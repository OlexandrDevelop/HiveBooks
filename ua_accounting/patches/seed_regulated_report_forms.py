"""Add dated versions for regulated report variants on existing sites."""

from ua_accounting.patches.seed_regulatory_forms import execute as seed_forms


def execute():
    seed_forms()
