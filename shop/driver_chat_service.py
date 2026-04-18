import sys

from .driver_chat import service as _driver_chat_service_module

sys.modules[__name__] = _driver_chat_service_module
