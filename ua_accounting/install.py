from ua_accounting.setup import seed


def before_install():
    seed.create_roles()


def after_install():
    seed.run()


def before_migrate():
    # roles must exist before doctypes and the workspace are synced
    seed.create_roles()


def after_migrate():
    seed.run()
