import sys

from .fcm import serializers as _fcm_serializers_module

sys.modules[__name__] = _fcm_serializers_module
