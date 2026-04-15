from django.db import transaction
from django.utils import timezone

from .models import AdminApprovalRequest
from .utils import build_absolute_file_url


def _shop_payload(shop_owner, request=None):
    return {
        "id": shop_owner.id,
        "shop_name": shop_owner.shop_name,
        "owner_name": shop_owner.owner_name,
        "shop_number": shop_owner.shop_number,
        "profile_image_url": build_absolute_file_url(getattr(shop_owner, "profile_image", None), request=request),
    }


def create_image_publish_request(image, request=None):
    payload = {
        "description": str(image.description or "").strip(),
        "image_url": build_absolute_file_url(getattr(image, "image", None), request=request),
        "changed_fields": ["image", "description"],
    }
    return AdminApprovalRequest.objects.create(
        shop_owner=image.shop_owner,
        request_type="image_publish",
        status="pending",
        payload=payload,
        gallery_image=image,
    )


def create_or_update_shop_edit_request(shop_owner, changes, request=None):
    pending_profile_image = changes.get("profile_image")
    if pending_profile_image is not None and not hasattr(pending_profile_image, "url"):
        pending_profile_image = None

    payload = {
        "owner_name": str(changes.get("owner_name") or shop_owner.owner_name or "").strip(),
        "shop_name": str(changes.get("shop_name") or shop_owner.shop_name or "").strip(),
        "phone_number": str(changes.get("phone_number") or shop_owner.phone_number or "").strip(),
        "description": str(changes.get("description") or shop_owner.description or "").strip(),
        "profile_image_url": build_absolute_file_url(pending_profile_image or getattr(shop_owner, "profile_image", None), request=request),
        "changed_fields": sorted([
            field
            for field in ("owner_name", "shop_name", "phone_number", "description", "profile_image")
            if field in changes
        ]),
    }
    approval_request, _ = AdminApprovalRequest.objects.update_or_create(
        shop_owner=shop_owner,
        request_type="shop_edit",
        status="pending",
        defaults={
            "payload": payload,
            "gallery_image": None,
            "offer": None,
            "reviewed_by": None,
            "reviewed_at": None,
            "rejection_reason": None,
        },
    )
    return approval_request


def create_or_update_offer_request(offer, request=None):
    payload = {
        "title": str(offer.title or "").strip(),
        "description": str(offer.description or "").strip(),
        "discount_percentage": str(offer.discount_percentage),
        "start_date": offer.start_date.isoformat() if offer.start_date else None,
        "end_date": offer.end_date.isoformat() if offer.end_date else None,
        "image_url": build_absolute_file_url(getattr(offer, "image", None), request=request),
        "is_active": bool(offer.is_active),
        "changed_fields": [
            "title",
            "description",
            "discount_percentage",
            "start_date",
            "end_date",
            "image",
        ],
    }
    approval_request, _ = AdminApprovalRequest.objects.update_or_create(
        offer=offer,
        request_type="offer",
        status="pending",
        defaults={
            "shop_owner": offer.shop_owner,
            "payload": payload,
            "gallery_image": None,
            "reviewed_by": None,
            "reviewed_at": None,
            "rejection_reason": None,
        },
    )
    return approval_request


def serialize_admin_approval_request(approval_request, request=None):
    shop_owner = approval_request.shop_owner
    payload = approval_request.payload or {}
    image_url = payload.get("image_url")
    if not image_url and approval_request.gallery_image_id:
        image_url = build_absolute_file_url(getattr(approval_request.gallery_image, "image", None), request=request)
    offer_image_url = payload.get("image_url")
    if not offer_image_url and approval_request.offer_id:
        offer_image_url = build_absolute_file_url(getattr(approval_request.offer, "image", None), request=request)

    return {
        "id": approval_request.id,
        "request_type": approval_request.request_type,
        "request_type_display": approval_request.get_request_type_display(),
        "change_scope": {
            "image_publish": "gallery_image",
            "shop_edit": "shop_profile",
            "offer": "offer",
        }.get(approval_request.request_type, approval_request.request_type),
        "changed_fields": payload.get("changed_fields") or [],
        "status": approval_request.status,
        "status_display": approval_request.get_status_display(),
        "created_at": approval_request.created_at,
        "updated_at": approval_request.updated_at,
        "reviewed_at": approval_request.reviewed_at,
        "rejection_reason": approval_request.rejection_reason,
        "shop": _shop_payload(shop_owner, request=request),
        "details": {
            "description": payload.get("description"),
            "owner_name": payload.get("owner_name"),
            "shop_name": payload.get("shop_name"),
            "phone_number": payload.get("phone_number"),
            "title": payload.get("title"),
            "discount_percentage": payload.get("discount_percentage"),
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
            "image_url": image_url if approval_request.request_type == "image_publish" else offer_image_url,
            "profile_image_url": payload.get("profile_image_url"),
        },
    }


@transaction.atomic
def review_approval_request(approval_request, admin_user, action, rejection_reason=""):
    if approval_request.status != "pending":
        return False

    if action == "approve":
        if approval_request.request_type == "image_publish" and approval_request.gallery_image_id:
            image = approval_request.gallery_image
            image.status = "published"
            image.save(update_fields=["status", "updated_at"])
        elif approval_request.request_type == "shop_edit":
            payload = approval_request.payload or {}
            shop_owner = approval_request.shop_owner
            update_fields = []
            for field in ("owner_name", "shop_name", "phone_number", "description"):
                if field in payload:
                    setattr(shop_owner, field, payload.get(field) or None)
                    update_fields.append(field)
            if update_fields:
                shop_owner.save(update_fields=update_fields)
        elif approval_request.request_type == "offer" and approval_request.offer_id:
            offer = approval_request.offer
            offer.is_active = True
            offer.save(update_fields=["is_active", "updated_at"])
        approval_request.status = "approved"
        approval_request.rejection_reason = None
    else:
        approval_request.status = "rejected"
        approval_request.rejection_reason = str(rejection_reason or "").strip() or None

    approval_request.reviewed_by = admin_user
    approval_request.reviewed_at = timezone.now()
    approval_request.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at", "updated_at"])
    return True
