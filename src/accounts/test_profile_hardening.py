import os
import shutil
import tempfile
from io import BytesIO
from unittest import mock

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import ProfileForm
from .models import User


def make_png(name='pic.png', size=(10, 10), noisy=False):
    """Build an uploaded PNG; noisy=True makes it large enough to trip a tiny size limit."""
    if noisy:
        image = Image.frombytes('RGB', size, os.urandom(size[0] * size[1] * 3))
    else:
        image = Image.new('RGB', size, color='blue')
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class MediaRootMixin:
    """Point MEDIA_ROOT at a throwaway directory that is removed after each test."""

    def setUp(self):
        super().setUp()
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.media_root = media_root


class ProfilePictureValidationTest(MediaRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='secret123')

    def test_oversized_image_is_rejected(self):
        with mock.patch('accounts.validators.MAX_PROFILE_PICTURE_BYTES', 1024):
            form = ProfileForm({}, {'profile_picture': make_png(size=(64, 64), noisy=True)}, instance=self.user)
            self.assertFalse(form.is_valid())
        self.assertIn('profile_picture', form.errors)
        self.assertIn('too large', form.errors['profile_picture'][0])

    def test_image_under_the_limit_is_accepted(self):
        form = ProfileForm({}, {'profile_picture': make_png()}, instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_non_image_upload_is_rejected(self):
        fake = SimpleUploadedFile('evil.png', b'this is not an image', content_type='image/png')
        form = ProfileForm({}, {'profile_picture': fake}, instance=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('profile_picture', form.errors)

    def test_revalidating_a_user_with_a_stored_picture_does_not_touch_storage(self):
        self.user.profile_picture.save('stored.png', make_png(), save=True)
        # Simulate the file vanishing from disk; full_clean must not crash on it.
        default_storage.delete(self.user.profile_picture.name)
        self.user.full_clean(exclude=['password'])


class ProfilePictureCleanupTest(MediaRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='secret123')
        self.client.force_login(self.user)

    def _post(self, **extra):
        return self.client.post(reverse('accounts:profile_editing'), extra)

    def _upload_first_picture(self):
        response = self._post(profile_picture=make_png('first.png'))
        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.refresh_from_db()
        return self.user.profile_picture.name

    def test_replacing_a_picture_deletes_the_old_file(self):
        first = self._upload_first_picture()
        self.assertTrue(default_storage.exists(first))

        self._post(profile_picture=make_png('second.png'))
        self.user.refresh_from_db()
        second = self.user.profile_picture.name

        self.assertNotEqual(first, second)
        self.assertTrue(default_storage.exists(second))
        self.assertFalse(default_storage.exists(first))

    def test_clearing_the_picture_deletes_the_file(self):
        first = self._upload_first_picture()

        self._post(**{'profile_picture-clear': 'on'})
        self.user.refresh_from_db()

        self.assertEqual(self.user.profile_picture.name, '')
        self.assertFalse(default_storage.exists(first))

    def test_saving_without_touching_the_picture_keeps_the_file(self):
        first = self._upload_first_picture()

        self._post(display_name='Alice')
        self.user.refresh_from_db()

        self.assertEqual(self.user.profile_picture.name, first)
        self.assertTrue(default_storage.exists(first))

    def test_failed_save_keeps_the_old_file(self):
        first = self._upload_first_picture()
        User.objects.create_user(username='bob', email='bob@example.com', password='secret123')

        # The email clash makes the form invalid, so nothing may be deleted.
        self._post(email='bob@example.com', profile_picture=make_png('second.png'))
        self.user.refresh_from_db()

        self.assertEqual(self.user.profile_picture.name, first)
        self.assertTrue(default_storage.exists(first))


class EmailUniquenessConstraintTest(TestCase):
    def test_database_rejects_emails_that_differ_only_by_case(self):
        User.objects.create_user(username='alice', email='dup@example.com', password='secret123')
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username='bob', email='DUP@Example.com', password='secret123')

    def test_many_users_may_have_a_blank_email(self):
        User.objects.create_user(username='alice', password='secret123')
        User.objects.create_user(username='bob', password='secret123')
        self.assertEqual(User.objects.filter(email='').count(), 2)

    def test_model_validation_reports_the_clash_too(self):
        # Covers code paths that skip our forms but call full_clean, such as the admin.
        User.objects.create_user(username='alice', email='dup@example.com', password='secret123')
        clash = User(username='bob', email='dup@example.com')
        with self.assertRaises(Exception) as ctx:
            clash.validate_constraints()
        self.assertIn('already exists', str(ctx.exception))
