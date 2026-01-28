from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .token_serializers import ShopOwnerTokenObtainPairSerializer
from .models import ShopOwner
from .utils import success_response, error_response


class ShopOwnerTokenObtainPairView(TokenObtainPairView):
    """
    تسجيل دخول صاحب المحل وإرجاع JWT Token
    POST /api/shop/login/
    Body: {
        "shop_number": "رقم المحل",
        "password": "كلمة المرور"
    }
    """
    serializer_class = ShopOwnerTokenObtainPairSerializer
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            errors = serializer.errors if hasattr(serializer, 'errors') else {'detail': str(e)}
            return error_response(
                message='فشل تسجيل الدخول',
                errors=errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        return success_response(
            data=serializer.validated_data,
            message='تم تسجيل الدخول بنجاح',
            status_code=status.HTTP_200_OK
        )


class ShopOwnerTokenRefreshView(TokenRefreshView):
    """
    تحديث JWT Token
    POST /api/shop/token/refresh/
    Body: {
        "refresh": "refresh_token"
    }
    """
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            errors = serializer.errors if hasattr(serializer, 'errors') else {'detail': str(e)}
            return error_response(
                message='فشل تحديث Token',
                errors=errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        return success_response(
            data=serializer.validated_data,
            message='تم تحديث Token بنجاح',
            status_code=status.HTTP_200_OK
        )

 