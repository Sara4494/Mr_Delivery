import sys

from .support_center import consumers as _support_center_consumers_module

sys.modules[__name__] = _support_center_consumers_module
