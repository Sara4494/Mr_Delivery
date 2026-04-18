import sys

from .driver_chat import consumers as _driver_chat_consumers_module

sys.modules[__name__] = _driver_chat_consumers_module
