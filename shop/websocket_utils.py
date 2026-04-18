import sys

from .realtime import websocket_utils as _websocket_utils_module

sys.modules[__name__] = _websocket_utils_module
