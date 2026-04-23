from django.db import transaction
from django.utils import timezone

from .models import AdminApprovalRequest
from .utils import build_absolute_file_url


SHOP_EDIT_FIELD_LABELS = {
    "owner_name": "اسم صاحب المحل",
    "shop_name": "اسم المحل",
    "phone_number": "رقم الهاتف",
    "description": "الوصف",
    "profile_image": "صورة البروفايل",
}


def _shop_payload(shop_owner, request=None):
    return {
        "id": shop_owner.id,
        "shop_name": shop_owner.shop_name,
        "profile_image_url": build_absolute_file_url(getattr(shop_owner, "profile_image", None), request=request),
    }


def _approval_details_text(approval_request, payload):
    if approval_request.request_type == "offer":
        return str(payload.get("description") or "").strip()
    if approval_request.request_type == "shop_edit":
        return str(payload.get("description") or "").strip()
    return str(payload.get("description") or "").strip()


def _approval_image_url(approval_request, request=None):
    payload = approval_request.payload or {}
    if approval_request.request_type == "image_publish":
        if payload.get("image_url"):
            return payload.get("image_url")
        if approval_request.gallery_image_id:
            return build_absolute_file_url(getattr(approval_request.gallery_image, "image", None), request=request)
        return None

    if approval_request.request_type == "offer":
        if payload.get("image_url"):
            return payload.get("image_url")
        if approval_request.offer_id:
            return build_absolute_file_url(getattr(approval_request.offer, "image", None), request=request)
        return None

    return payload.get("profile_image_url")


def _get_shop_edit_field_values(shop_owner, changes):
    return {
        "owner_name": str(getattr(shop_owner, "owner_name", "") or "").strip(),
        "shop_name": str(getattr(shop_owner, "shop_name", "") or "").strip(),
        "phone_number": str(getattr(shop_owner, "phone_number", "") or "").strip(),
        "description": str(getattr(shop_owner, "description", "") or "").strip(),
        "profile_image_url": build_absolute_file_url(getattr(shop_owner, "profile_image", None)),
    }


def _build_shop_edit_requested_changes(shop_owner, changes, request=None):
    current_values = _get_shop_edit_field_values(shop_owner, changes)
    requested_changes = []

    for field in ("owner_name", "shop_name", "phone_number", "description"):
        if field not in changes:
            continue
        old_value = current_values.get(field)
        new_value = str(changes.get(field) or "").strip()
        requested_changes.append(
            {
                "field": field,
                "label": SHOP_EDIT_FIELD_LABELS.get(field, field),
                "old_value": old_value,
                "new_value": new_value,
            }
        )

    if "profile_image" in changes:
        requested_changes.append(
            {
                "field": "profile_image",
                "label": SHOP_EDIT_FIELD_LABELS["profile_image"],
                "old_value": current_values.get("profile_image_url"),
                "new_value": build_absolute_file_url(changes.get("profile_image"), request=request),
            }
        )

    return current_values, requested_changes


def serialize_shop_approval_request_summary(approval_request, request=None):
    if not approval_request:
        return None

    payload = approval_request.payload or {}
    return {
        "id": approval_request.id,
        "request_type": approval_request.request_type,
        "request_type_display": approval_request.get_request_type_display(),
        "status": approval_request.status,
        "status_display": approval_request.get_status_display(),
        "details": _approval_details_text(approval_request, payload),
        "image_url": _approval_image_url(approval_request, request=request),
        "changed_fields": payload.get("changed_fields") or [],
        "requested_changes": payload.get("requested_changes") or [],
        "current_values": payload.get("current_values") or {},
        "rejection_reason": approval_request.rejection_reason,
        "created_at": approval_request.created_at,
        "reviewed_at": approval_request.reviewed_at,
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

    current_values, requested_changes = _build_shop_edit_requested_changes(shop_owner, changes, request=request)

    payload = {
        "owner_name": str(changes.get("owner_name") or shop_owner.owner_name or "").strip(),
        "shop_name": str(changes.get("shop_name") or shop_owner.shop_name or "").strip(),
        "phone_number": str(changes.get("phone_number") or shop_owner.phone_number or "").strip(),
        "description": str(changes.get("description") or shop_owner.description or "").strip(),
        "profile_image_url": build_absolute_file_url(pending_profile_image or getattr(shop_owner, "profile_image", None), request=request),
        "current_values": current_values,
        "requested_changes": requested_changes,
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
    payload = approval_request.payload or {}
    return {
        "id": approval_request.id,
        "shop_name": approval_request.shop_owner.shop_name,
        "shop_image_url": build_absolute_file_url(getattr(approval_request.shop_owner, "profile_image", None), request=request),
        "request_type": approval_request.request_type,
        "request_type_display": approval_request.get_request_type_display(),
        "details": _approval_details_text(approval_request, payload),
        "request_date": approval_request.created_at.date().isoformat() if approval_request.created_at else None,
        "status": approval_request.status,
        "status_display": approval_request.get_status_display(),
        "changed_fields": payload.get("changed_fields") or [],
        "requested_changes": payload.get("requested_changes") or [],
        "rejection_reason": approval_request.rejection_reason,
    }


def serialize_admin_approval_request_detail(approval_request, request=None):
    payload = approval_request.payload or {}
    image_url = _approval_image_url(approval_request, request=request)

    return {
        "id": approval_request.id,
        "shop_name": approval_request.shop_owner.shop_name,
        "shop_image_url": build_absolute_file_url(getattr(approval_request.shop_owner, "profile_image", None), request=request),
        "request_type": approval_request.request_type,
        "request_type_display": approval_request.get_request_type_display(),
        "request_date": approval_request.created_at.date().isoformat() if approval_request.created_at else None,
        "status": approval_request.status,
        "status_display": approval_request.get_status_display(),
        "details": _approval_details_text(approval_request, payload),
        "image_url": image_url,
        "discount_percentage": payload.get("discount_percentage"),
        "rejection_reason": approval_request.rejection_reason,
        "changed_fields": payload.get("changed_fields") or [],
        "requested_changes": payload.get("requested_changes") or [],
        "current_values": payload.get("current_values") or {},
        "meta": {
            "title": payload.get("title"),
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
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
