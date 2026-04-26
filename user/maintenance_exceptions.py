from rest_framework import status
from rest_framework.exceptions import APIException
from .models import APP_MAINTENANCE_RESPONSE_CODE


class MaintenanceModeError(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = APP_MAINTENANCE_RESPONSE_CODE
    default_detail = "التطبيق تحت الصيانة حاليًا. يرجى المحاولة لاحقًا."