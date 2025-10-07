from django.conf import settings
from django.core.checks import Error, register


@register()
def debug_disabled_in_production(app_configs, **kwargs):
    """Ensure DEBUG is disabled when running in production."""
    if getattr(settings, 'ENV', '').lower() == 'production' and settings.DEBUG:
        return [
            Error(
                'DEBUG must be False when ENV is set to production.',
                id='chat.E001',
            )
        ]
    return []
