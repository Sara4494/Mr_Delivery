import sys

from .driver_chat import views as _driver_chat_views_module

sys.modules[__name__] = _driver_chat_views_module
