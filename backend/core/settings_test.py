from .settings import *  # noqa: F401,F403


MIGRATION_MODULES = dict(globals().get("MIGRATION_MODULES", {}))
MIGRATION_MODULES["chat"] = None
