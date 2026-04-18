import sys

from .realtime import customer_app as _customer_app_module

sys.modules[__name__] = _customer_app_module
