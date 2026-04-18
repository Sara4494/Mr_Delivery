import sys

from .fcm import views as _fcm_views_module

sys.modules[__name__] = _fcm_views_module
