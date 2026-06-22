from .settings import *  # noqa: F401,F403


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'test_db.sqlite3',
    }
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}

MIGRATION_MODULES = {
    'admin_desktop_app': None,
    'customer_app': None,
    'driver_app': None,
    'gallery': None,
    'platform_core': None,
    'shop': None,
    'shop_app': None,
    'support_center': None,
    'user': None,
}
