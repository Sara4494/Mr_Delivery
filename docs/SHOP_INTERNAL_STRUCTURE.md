# Shop Internal Structure

The `shop` app now keeps feature-specific modules inside dedicated packages while
preserving the old import paths for backward compatibility.

## Domain packages

- `shop/core/`
  - authentication and permissions
- `shop/realtime/`
  - customer realtime
  - driver realtime
  - presence helpers
  - websocket utilities
  - realtime serializers
- `shop/driver_chat/`
  - driver chat service
  - driver chat websocket consumers
  - driver chat API views
- `shop/fcm/`
  - FCM serializers
  - FCM service
  - FCM API views
- `shop/support_center/`
  - support center service
  - support center websocket consumers
  - support center serializers
  - support center API views and payload builders

## Compatibility layer

Top-level modules such as `shop/fcm_service.py` and `shop/driver_realtime.py`
remain in place as thin aliases to the new modules. This keeps existing imports,
tests, and patches working while the codebase transitions to the organized
package layout.

## Large files still at root

These files were intentionally left in place for now because moving them safely
requires a second pass with broader dependency updates:

- `shop/models.py`
- `shop/serializers.py`
- `shop/views.py`
- `shop/consumers.py`
- `shop/middleware.py`

The next safe refactor step is to extract sections from those large files into
feature packages one domain at a time, while keeping a compatibility import
surface at the root.

## Already extracted from large files

- Support-center serializers were moved out of `shop/serializers.py`
- Support-center API views and payload builders were moved out of `shop/views.py`
- Shared actor resolution helpers were centralized in `shop/core/identity.py`
