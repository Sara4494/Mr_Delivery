import sys

from .fcm import service as _fcm_service_module

sys.modules[__name__] = _fcm_service_module
