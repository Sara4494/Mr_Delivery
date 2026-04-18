import sys

from .realtime import presence as _presence_module

sys.modules[__name__] = _presence_module
