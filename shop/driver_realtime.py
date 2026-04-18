import sys

from .realtime import driver as _driver_realtime_module

sys.modules[__name__] = _driver_realtime_module
