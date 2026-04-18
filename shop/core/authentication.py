from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed
from ..models import Employee, Driver
from user.models import ShopOwner


class EmployeeJWTAuthentication(JWTAuthentication):
    """Custom JWT Authentication للموظف"""
    
    def get_user(self, validated_token):
        """
        الحصول على Employee من validated token
        """
        try:
            employee_id = validated_token.get('employee_id')
            user_type = validated_token.get('user_type')
            
            if not employee_id or user_type != 'employee':
                raise InvalidToken('Token does not contain employee_id or invalid user_type')
            
            employee = Employee.objects.get(id=employee_id, is_active=True)
            return employee
        except Employee.DoesNotExist:
            raise AuthenticationFailed('Employee not found or inactive')
        except KeyError:
            raise InvalidToken('Invalid token format')


class DriverJWTAuthentication(JWTAuthentication):
    """Custom JWT Authentication للسائق"""
    
    def get_user(self, validated_token):
        """
        الحصول على Driver من validated token
        """
        try:
            driver_id = validated_token.get('driver_id')
            user_type = validated_token.get('user_type')
            
            if not driver_id or user_type != 'driver':
                raise InvalidToken('Token does not contain driver_id or invalid user_type')
            
            driver = Driver.objects.get(id=driver_id)
            return driver
        except Driver.DoesNotExist:
            raise AuthenticationFailed('Driver not found')
        except KeyError:
            raise InvalidToken('Invalid token format')
