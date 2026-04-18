import sys

from .core import authentication as _authentication_module

sys.modules[__name__] = _authentication_module
