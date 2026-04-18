"""Shared helpers for resolving authenticated actor identity."""

from user.models import ShopOwner

from ..models import Customer, Driver, Employee


def resolve_user_type(user):
    user_type = getattr(user, 'user_type', None)
    if user_type in {'customer', 'shop_owner', 'employee', 'driver'}:
        return user_type
    if isinstance(user, Customer):
        return 'customer'
    if isinstance(user, ShopOwner):
        return 'shop_owner'
    if isinstance(user, Employee):
        return 'employee'
    if isinstance(user, Driver):
        return 'driver'
    return None


def resolve_customer_user(user):
    if isinstance(user, Customer):
        return user
    try:
        return Customer.objects.get(id=user.id)
    except (Customer.DoesNotExist, AttributeError):
        return None


def resolve_shop_owner_or_employee_owner(user):
    user_type = getattr(user, 'user_type', None)
    if user_type == 'shop_owner':
        return user
    if user_type == 'employee':
        return getattr(user, 'shop_owner', None)

    if isinstance(user, ShopOwner):
        return user
    if isinstance(user, Employee):
        return getattr(user, 'shop_owner', None)
    return None
