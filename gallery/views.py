from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Count, Sum
from django.shortcuts import get_object_or_404
from .models import GalleryImage, WorkSchedule, ImageLike
<<<<<<< HEAD
from .serializers import (
=======
from .serializers import (
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
    GalleryImageSerializer,
    GalleryImageCreateSerializer,
    WorkScheduleSerializer,
    ShopProfileSerializer,
    ShopProfileUpdateSerializer,
    ImageLikeSerializer
<<<<<<< HEAD
)
from user.models import ShopOwner
from shop.models import Employee
from user.utils import success_response, error_response, build_message_fields, t


class GalleryPagination(PageNumberPagination):
=======
)
from user.models import ShopOwner
from user.authentication import ShopOwnerJWTAuthentication
from user.utils import success_response, error_response


class GalleryPagination(PageNumberPagination):
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
    """Pagination لمعرض الصور"""
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 100
    
    def get_paginated_response(self, data):
        """تخصيص شكل الـ response للـ pagination"""
        from rest_framework.response import Response
        from rest_framework import status
        
<<<<<<< HEAD
        response_data = {
            "status": status.HTTP_200_OK,
            **build_message_fields(
                t(getattr(self, "request", None), "images_retrieved_successfully"),
                request=getattr(self, "request", None)
            ),
            "data": {
                'count': self.page.paginator.count,
                'next': self.get_next_link(),
                'previous': self.get_previous_link(),
=======
        response_data = {
            "status": status.HTTP_200_OK,
            "message": "تم جلب الصور بنجاح",
            "data": {
                'count': self.page.paginator.count,
                'next': self.get_next_link(),
                'previous': self.get_previous_link(),
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
                'results': data
            }
        }
        
<<<<<<< HEAD
        return Response(response_data, status=status.HTTP_200_OK)


def _is_shop_owner(user):
    user_type = getattr(user, 'user_type', None)
    return user_type == 'shop_owner' or isinstance(user, ShopOwner)


def _is_employee(user):
    user_type = getattr(user, 'user_type', None)
    return user_type == 'employee' or isinstance(user, Employee)


def _is_cashier(user):
    return _is_employee(user) and getattr(user, 'role', None) == 'cashier'


def _resolve_shop_owner(user):
    if _is_shop_owner(user):
        return user
    if _is_employee(user):
        return getattr(user, 'shop_owner', None)
    return None


def _forbidden(request, message_key):
    return error_response(
        message=t(request, message_key),
        status_code=status.HTTP_403_FORBIDDEN
    )


@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def shop_profile_view(request):
    """
    عرض وتحديث ملف صاحب المحل (البيانات + صورة البروفيل في endpoint واحد).
    الأونر فقط يقدر يعدّل عليه.
    GET /api/shop/profile/ - عرض الملف الشخصي
    PUT/PATCH /api/shop/profile/ - تحديث الملف الشخصي (owner_name, shop_name، و/أو profile_image)
    Body: application/json { "owner_name", "shop_name" } أو multipart/form-data مع profile_image (اختياري)
    """
    user = request.user
    shop_owner = _resolve_shop_owner(user)
    if not shop_owner:
        return _forbidden(request, 'permission_only_shop_owner_or_cashier')

    if request.method == 'GET':
        if not (_is_shop_owner(user) or _is_cashier(user)):
            return _forbidden(request, 'permission_only_shop_owner_or_cashier')

        serializer = ShopProfileSerializer(shop_owner, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'profile_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )

    elif request.method in ('PUT', 'PATCH'):
        if not _is_shop_owner(user):
            return _forbidden(request, 'permission_only_shop_owner_edit_content')

        data = request.data.copy()
        if request.FILES.get('profile_image'):
            data['profile_image'] = request.FILES['profile_image']

=======
        return Response(response_data, status=status.HTTP_200_OK)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def shop_profile_view(request):
    """
    عرض وتحديث ملف صاحب المحل
    GET /api/shop/profile/ - عرض الملف الشخصي
    PUT /api/shop/profile/ - تحديث الملف الشخصي (بدون صورة البروفيل)
    """
    shop_owner = request.user
    
    if request.method == 'GET':
        serializer = ShopProfileSerializer(shop_owner, context={'request': request})
        return success_response(
            data=serializer.data,
            message='تم جلب الملف الشخصي بنجاح',
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        # إزالة profile_image من البيانات لأن له endpoint منفصل
        data = request.data.copy()
        if 'profile_image' in data:
            data.pop('profile_image')
        
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
        serializer = ShopProfileUpdateSerializer(shop_owner, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            profile_serializer = ShopProfileSerializer(shop_owner, context={'request': request})
            return success_response(
                data=profile_serializer.data,
<<<<<<< HEAD
                message=t(request, 'profile_updated_successfully'),
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message=t(request, 'invalid_data'),
=======
                message='تم تحديث الملف الشخصي بنجاح',
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message='بيانات غير صحيحة',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


<<<<<<< HEAD
@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def work_schedule_view(request):
=======
@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def shop_profile_image_view(request):
    """
    تحديث صورة البروفيل فقط
    PUT /api/shop/profile/image/
    Body (multipart/form-data): {
        "profile_image": [file]
    }
    """
    shop_owner = request.user
    
    if 'profile_image' not in request.data:
        return error_response(
            message='صورة البروفيل مطلوبة',
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    shop_owner.profile_image = request.data['profile_image']
    shop_owner.save()
    
    profile_serializer = ShopProfileSerializer(shop_owner, context={'request': request})
    return success_response(
        data=profile_serializer.data,
        message='تم تحديث صورة البروفيل بنجاح',
        status_code=status.HTTP_200_OK
    )


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def work_schedule_view(request):
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
    """
    عرض وتحديث مواعيد العمل
    GET /api/shop/schedule/ - عرض مواعيد العمل
    PUT /api/shop/schedule/ - تحديث مواعيد العمل
    """
<<<<<<< HEAD
    user = request.user
    shop_owner = _resolve_shop_owner(user)
    if not shop_owner:
        return _forbidden(request, 'permission_only_shop_owner')
    
    schedule, created = WorkSchedule.objects.get_or_create(shop_owner=shop_owner)
    
    if request.method == 'GET':
        if not (_is_shop_owner(user) or _is_cashier(user)):
            return _forbidden(request, 'permission_only_shop_owner_or_cashier')

        serializer = WorkScheduleSerializer(schedule)
        return success_response(
            data=serializer.data,
            message=t(request, 'work_schedule_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        if not _is_shop_owner(user):
            return _forbidden(request, 'permission_only_shop_owner_edit_content')

        serializer = WorkScheduleSerializer(schedule, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success_response(
                data=serializer.data,
                message=t(request, 'work_schedule_updated_successfully'),
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message=t(request, 'invalid_data'),
=======
    shop_owner = request.user
    
    schedule, created = WorkSchedule.objects.get_or_create(shop_owner=shop_owner)
    
    if request.method == 'GET':
        serializer = WorkScheduleSerializer(schedule)
        return success_response(
            data=serializer.data,
            message='تم جلب مواعيد العمل بنجاح',
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        serializer = WorkScheduleSerializer(schedule, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success_response(
                data=serializer.data,
                message='تم تحديث مواعيد العمل بنجاح',
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message='بيانات غير صحيحة',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


<<<<<<< HEAD
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def gallery_list_view(request):
=======
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def gallery_list_view(request):
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
    """
    عرض قائمة الصور وإضافة صورة جديدة
    GET /api/shop/gallery/ - عرض قائمة الصور (مع pagination و sorting)
    POST /api/shop/gallery/ - إضافة صورة جديدة
    """
<<<<<<< HEAD
    user = request.user
    shop_owner = _resolve_shop_owner(user)
    if not shop_owner:
        return _forbidden(request, 'permission_only_shop_owner_or_cashier')
    
    if request.method == 'GET':
        if not (_is_shop_owner(user) or _is_cashier(user)):
            return _forbidden(request, 'permission_only_shop_owner_or_cashier')

        # Filtering
        status_filter = request.query_params.get('status')
        search_query = request.query_params.get('search')
=======
    shop_owner = request.user
    
    if request.method == 'GET':
        # Filtering
        status_filter = request.query_params.get('status')
        search_query = request.query_params.get('search')
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
        
        queryset = GalleryImage.objects.filter(shop_owner=shop_owner)
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        if search_query:
            queryset = queryset.filter(description__icontains=search_query)
        
        # Sorting
        sort_by = request.query_params.get('sort_by', '-uploaded_at')
        if sort_by.lstrip('-') in ['uploaded_at', 'likes_count', 'updated_at']:
            queryset = queryset.order_by(sort_by)
        
        # Pagination
        paginator = GalleryPagination()
        page = paginator.paginate_queryset(queryset, request)
        
        if page is not None:
            serializer = GalleryImageSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = GalleryImageSerializer(queryset, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
<<<<<<< HEAD
            message=t(request, 'images_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'POST':
        if not _is_shop_owner(user):
            return _forbidden(request, 'permission_only_shop_owner')

        serializer = GalleryImageCreateSerializer(
            data=request.data,
            context={'shop_owner': shop_owner, 'request': request}
=======
            message='تم جلب الصور بنجاح',
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'POST':
        serializer = GalleryImageCreateSerializer(
            data=request.data,
            context={'shop_owner': shop_owner, 'request': request}
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
        )
        if serializer.is_valid():
            image = serializer.save()
            response_serializer = GalleryImageSerializer(image, context={'request': request})
            return success_response(
                data=response_serializer.data,
<<<<<<< HEAD
                message=t(request, 'image_uploaded_successfully'),
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message=t(request, 'invalid_data'),
=======
                message='تم رفع الصورة بنجاح',
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message='بيانات غير صحيحة',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


<<<<<<< HEAD
@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def gallery_detail_view(request, image_id):
=======
@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def gallery_detail_view(request, image_id):
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
    """
    عرض، تحديث، أو حذف صورة محددة
    GET /api/shop/gallery/{id}/ - عرض صورة
    PUT /api/shop/gallery/{id}/ - تحديث صورة
    DELETE /api/shop/gallery/{id}/ - حذف صورة
    """
<<<<<<< HEAD
    user = request.user
    shop_owner = _resolve_shop_owner(user)
    if not shop_owner:
        return _forbidden(request, 'permission_only_shop_owner_or_cashier')
    
    try:
        image = GalleryImage.objects.get(id=image_id, shop_owner=shop_owner)
    except GalleryImage.DoesNotExist:
        return error_response(
            message=t(request, 'image_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        if not (_is_shop_owner(user) or _is_cashier(user)):
            return _forbidden(request, 'permission_only_shop_owner_or_cashier')

        serializer = GalleryImageSerializer(image, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'image_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        if _is_cashier(user):
            allowed_keys = {'status'}
            payload_keys = set(request.data.keys())
            if not payload_keys.issubset(allowed_keys):
                return _forbidden(request, 'cashier_can_only_publish_images')

            if request.data.get('status') != 'published':
                return _forbidden(request, 'cashier_can_only_publish_images')

            image.status = 'published'
            image.save()
            response_serializer = GalleryImageSerializer(image, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'image_updated_successfully'),
                status_code=status.HTTP_200_OK
            )

        if not _is_shop_owner(user):
            return _forbidden(request, 'permission_only_shop_owner')

        serializer = GalleryImageCreateSerializer(image, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            response_serializer = GalleryImageSerializer(image, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'image_updated_successfully'),
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message=t(request, 'invalid_data'),
=======
    shop_owner = request.user
    
    try:
        image = GalleryImage.objects.get(id=image_id, shop_owner=shop_owner)
    except GalleryImage.DoesNotExist:
        return error_response(
            message='الصورة غير موجودة',
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        serializer = GalleryImageSerializer(image, context={'request': request})
        return success_response(
            data=serializer.data,
            message='تم جلب الصورة بنجاح',
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        serializer = GalleryImageCreateSerializer(image, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            response_serializer = GalleryImageSerializer(image, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message='تم تحديث الصورة بنجاح',
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message='بيانات غير صحيحة',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
<<<<<<< HEAD
    elif request.method == 'DELETE':
        if not _is_shop_owner(user):
            return _forbidden(request, 'permission_only_shop_owner')

        image.delete()
        return success_response(
            message=t(request, 'image_deleted_successfully'),
=======
    elif request.method == 'DELETE':
        image.delete()
        return success_response(
            message='تم حذف الصورة بنجاح',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
            status_code=status.HTTP_200_OK
        )


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def image_like_view(request, image_id):
    """
    إعجاب أو إلغاء إعجاب بصورة
    POST /api/shop/gallery/{id}/like/ - إعجاب بالصورة
    DELETE /api/shop/gallery/{id}/like/ - إلغاء الإعجاب
    """
    shop_owner = request.user
    user_identifier = request.data.get('user_identifier', str(shop_owner.id))
    
    try:
        image = GalleryImage.objects.get(id=image_id, shop_owner=shop_owner, status='published')
    except GalleryImage.DoesNotExist:
        return error_response(
<<<<<<< HEAD
            message=t(request, 'image_not_found'),
=======
            message='الصورة غير موجودة',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'POST':
        like, created = ImageLike.objects.get_or_create(
            image=image,
            user_identifier=user_identifier
        )
        if created:
            image.likes_count += 1
            image.save()
            return success_response(
                data={'liked': True},
<<<<<<< HEAD
                message=t(request, 'image_liked_successfully'),
=======
                message='تم الإعجاب بالصورة',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
                status_code=status.HTTP_201_CREATED
            )
        else:
            return error_response(
<<<<<<< HEAD
                message=t(request, 'this_image_has_already_been_liked'),
=======
                message='تم الإعجاب بهذه الصورة مسبقاً',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
                status_code=status.HTTP_400_BAD_REQUEST
            )
    
    elif request.method == 'DELETE':
        try:
            like = ImageLike.objects.get(image=image, user_identifier=user_identifier)
            like.delete()
            image.likes_count = max(0, image.likes_count - 1)
            image.save()
            return success_response(
                data={'liked': False},
<<<<<<< HEAD
                message=t(request, 'like_removed_successfully'),
=======
                message='تم إلغاء الإعجاب',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
                status_code=status.HTTP_200_OK
            )
        except ImageLike.DoesNotExist:
            return error_response(
<<<<<<< HEAD
                message=t(request, 'this_image_was_not_liked'),
=======
                message='لم يتم الإعجاب بهذه الصورة',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
                status_code=status.HTTP_404_NOT_FOUND
            )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def shop_statistics_view(request):
    """
    إحصائيات المحل
    GET /api/shop/statistics/ - عرض إحصائيات المحل
    """
    shop_owner = request.user
    
    total_images = shop_owner.gallery_images.count()
    published_images = shop_owner.gallery_images.filter(status='published').count()
    draft_images = shop_owner.gallery_images.filter(status='draft').count()
    total_likes = shop_owner.gallery_images.filter(status='published').aggregate(
        total=Sum('likes_count')
    )['total'] or 0
    
    return success_response(
        data={
            'total_images': total_images,
            'published_images': published_images,
            'draft_images': draft_images,
            'total_likes': total_likes
        },
<<<<<<< HEAD
        message=t(request, 'statistics_retrieved_successfully'),
=======
        message='تم جلب الإحصائيات بنجاح',
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
        status_code=status.HTTP_200_OK
    )
