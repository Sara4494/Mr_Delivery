import sys

from .realtime import serializers as _realtime_serializers_module

sys.modules[__name__] = _realtime_serializers_module
