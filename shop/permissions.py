import sys

from .core import permissions as _permissions_module

sys.modules[__name__] = _permissions_module
