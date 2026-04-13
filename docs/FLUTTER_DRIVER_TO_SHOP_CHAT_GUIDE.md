# Flutter Driver To Shop Chat Guide

This document is only for:

- Driver -> Shop

This flow uses the dedicated driver-shop chats module, not the order chat socket.

## Transport

WebSocket used by the driver app:

```text
/ws/driver-chats/driver/{driver_id}/?token=<JWT>&lang=ar
```

This socket is different from:

```text
/ws/chat/order/{order_id}/?chat_type=driver_customer
```

because that second one is only for driver <-> customer.

## Purpose

The driver-shop chat is used for:

- realtime conversation between driver and shop
- order transfer requests
- driver/shop operational coordination
- voice uploads in the driver-shop module
- shop-side conversation updates

## Main Driver-Side Endpoints

The backend already documents this larger flow in:

- `docs/FLUTTER_DRIVER_APP_CHAT_GUIDE.md`

Important routes currently present in backend:

- `POST /api/driver/driver-chats/voice/upload/`
- websocket: `/ws/driver-chats/driver/{driver_id}/?token=<JWT>&lang=ar`

Shop-side related routes also exist under:

- `/api/shop/driver-chats/...`

## Driver -> Shop Message Direction

In this module, the driver sends messages to the shop conversation thread.

That means this file focuses on:

1. Driver -> Shop
   The driver sends a message/event into the dedicated driver-shop conversation.

The reverse direction also exists operationally, but that is not the focus of this file.

## What Flutter Should Use

Use the dedicated driver-shop socket service for:

- shop conversation snapshot
- incoming shop messages
- outgoing driver messages
- transfer requests
- call signaling if implemented in app

Do not use `chat_type=driver_customer` here.

## Recommended Reference

For full driver-shop message/event contract, use:

- [FLUTTER_DRIVER_APP_CHAT_GUIDE.md](./FLUTTER_DRIVER_APP_CHAT_GUIDE.md)

This file is the short directional guide telling the team:

- this is the driver -> shop path
- it uses `/ws/driver-chats/driver/{driver_id}/`
- it is separate from driver -> customer

## Related Docs

- [FLUTTER_DRIVER_TO_CUSTOMER_CHAT_GUIDE.md](./FLUTTER_DRIVER_TO_CUSTOMER_CHAT_GUIDE.md)
- [FLUTTER_DRIVER_CHATS_GUIDE.md](./FLUTTER_DRIVER_CHATS_GUIDE.md)
- [FLUTTER_DRIVER_APP_CHAT_GUIDE.md](./FLUTTER_DRIVER_APP_CHAT_GUIDE.md)
