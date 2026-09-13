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
        # The login view arrives with feat/auth (US-01), so this branch can only
        # assert where we send the user, not that the page renders.
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(settings.LOGIN_URL))
        self.assertIn('next=' + reverse('accounts:profile'), response.url)

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

    def test_email_already_used_by_someone_else_is_rejected(self):
        User.objects.create_user(username='bob', email='bob@example.com', password='secret123')
        form = ProfileForm({'email': 'BOB@example.com'}, instance=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_own_email_and_blank_email_are_accepted(self):
        form = ProfileForm({'email': self.user.email}, instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        form = ProfileForm({'email': ''}, instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)
