from rest_framework.response import Response
from rest_framework import status as http_status


def success_response(data=None, message="", status_code=http_status.HTTP_200_OK):
    """
    إنشاء response ناجح
    """
    response_data = {
        "status": status_code,
        "message": message,
        "data": data if data is not None else {}
    }
    return Response(response_data, status=status_code)


def error_response(message="", errors=None, status_code=http_status.HTTP_400_BAD_REQUEST):
    """
    إنشاء response خطأ
    """
    response_data = {
        "status": status_code,
        "message": message,
        "data": {}
    }
    if errors:
        response_data["errors"] = errors
    return Response(response_data, status=status_code)
