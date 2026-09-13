import tempfile
from io import BytesIO

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import ProfileForm
from .models import User


class ProfilePictureAcceptanceTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='alice',
            email='alice@example.com',
            password='secret123',
        )

    def test_anonymous_get_redirects_to_login(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_authenticated_get_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/profile.html')

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_post_with_simple_uploaded_file_returns_302_and_saves_picture(self):
        self.client.force_login(self.user)

        image = Image.new('RGB', (10, 10), color='blue')
        image_bytes = BytesIO()
        image.save(image_bytes, format='PNG')
        image_bytes.seek(0)

        uploaded = SimpleUploadedFile(
            'profile.png',
            image_bytes.read(),
            content_type='image/png',
        )

        response = self.client.post(
            reverse('accounts:profile'),
            {
                'display_name': 'Alice',
                'favorite_boardgame': 'Catan',
                'favorite_genre': 'strategy',
                'known_boardgames': 'Catan, Ticket to Ride',
                'bio': 'Hello world',
                'profile_picture': uploaded,
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('accounts:profile'))

        self.user.refresh_from_db()
        self.assertTrue(self.user.profile_picture.name)
        self.assertIn('profile.png', self.user.profile_picture.name)

    def test_profile_form_includes_profile_picture_field(self):
        form = ProfileForm()
        self.assertIn('profile_picture', form.fields)

    def test_user_model_has_profile_picture_field_imagefield(self):
        field = User._meta.get_field('profile_picture')
        self.assertTrue(field.__class__.__name__ == 'ImageField')
