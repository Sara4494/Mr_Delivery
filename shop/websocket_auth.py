import json

from channels.db import database_sync_to_async

from user.account_status import get_account_suspension_context


@database_sync_to_async
def _refresh_account_suspension(user, lang=None):
    return get_account_suspension_context(user, lang=lang)


async def ensure_socket_account_active(consumer, *, close_code=4403, refresh=False, accept_if_needed=False):
    suspension = None
    if refresh and getattr(consumer, "user", None):
        suspension = await _refresh_account_suspension(consumer.user, lang=getattr(consumer, "lang", None))
    else:
        suspension = (getattr(consumer, "scope", None) or {}).get("account_suspension")

    if not suspension:
        return True

    if accept_if_needed:
        await consumer.accept()
    payload = {
        "type": "account_suspended",
        "code": suspension.get("code", "account_suspended"),
        "message": suspension.get("detail"),
    }
    if suspension.get("reason"):
        payload["reason"] = suspension["reason"]
    await consumer.send(text_data=json.dumps(payload))
    await consumer.close(code=close_code)
    return False
