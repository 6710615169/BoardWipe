from django.test import TestCase
from django.db.models import ImageField

from .forms import ProfileForm
from .models import User


class ProfilePictureAcceptanceTest(TestCase):
    def test_profile_form_includes_profile_picture_field(self):
        form = ProfileForm()
        self.assertIn('profile_picture', form.fields)

    def test_user_model_has_profile_picture_field(self):
        field = User._meta.get_field('profile_picture')
        self.assertIsInstance(field, ImageField)
