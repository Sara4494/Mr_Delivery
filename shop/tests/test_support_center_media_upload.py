import shutil
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from django.core.files.uploadedfile import SimpleUploadedFile

from shop.models import ShopSupportTicket
from user.models import ShopCategory, ShopOwner


TEMP_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT, ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class SupportCenterMediaUploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()
        self.category = ShopCategory.objects.create(name='Support Upload Category')
        self.shop = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Upload Test Shop',
            shop_number='SHOP-UPLOAD-1',
            phone_number='01010000101',
            password='secret123',
            shop_category=self.category,
        )
        self.shop.user_type = 'shop_owner'
        self.ticket = ShopSupportTicket.objects.create(
            shop_owner=self.shop,
            subject='Image upload issue',
            priority='high',
            status='open',
        )
        self.client.force_authenticate(user=self.shop)

    def test_ticket_media_upload_accepts_generic_file_and_media_type(self):
        response = self.client.post(
            reverse('shop:support_ticket_media_upload', kwargs={'ticket_id': self.ticket.public_id}),
            data={
                'media_type': 'image',
                'content': 'Screenshot attached',
                'file': SimpleUploadedFile('issue.jpg', b'fake-image-bytes', content_type='image/jpeg'),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()['data']
        self.assertEqual(payload['ticket_id'], self.ticket.public_id)
        self.assertEqual(payload['message_type'], 'image')
        self.assertEqual(payload['content'], 'Screenshot attached')
        self.assertIn('/media/support_center/images/', payload['image_url'])

    def test_support_route_falls_back_to_ticket_upload_when_ticket_id_is_present(self):
        response = self.client.post(
            reverse('shop:support_chat_media_upload', kwargs={'conversation_id': 'support_2'}),
            data={
                'ticket_id': self.ticket.public_id,
                'conversation_id': self.ticket.public_id,
                'media_type': 'image',
                'file': SimpleUploadedFile('issue-2.jpg', b'fake-image-bytes-2', content_type='image/jpeg'),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()['data']
        self.assertEqual(payload['ticket_id'], self.ticket.public_id)
        self.assertEqual(payload['message_type'], 'image')
