import sys

from .support_center import service as _support_center_service_module

sys.modules[__name__] = _support_center_service_module
