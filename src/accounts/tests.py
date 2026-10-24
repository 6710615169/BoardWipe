import tempfile
from io import BytesIO

from django.conf import settings
from django.contrib.auth.forms import PasswordChangeForm
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image
from .models import User

from .forms import ProfileForm
from .models import User

class ProfileSearchTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user('me', password='pass12345')
        self.alice = User.objects.create_user(
            'alice', password='x', favorite_genre='strategy',
            known_boardgames='Catan, Chess',owned_boardgames='Catan, Gloomhaven')
        self.bob = User.objects.create_user(
            'bob', password='x', favorite_genre='party',
            known_boardgames='Codenames',owned_boardgames='Uno')
        self.dave = User.objects.create_user(
            'dave', password='x', favorite_genre='strategy', is_active=False)
        self.client.login(username='me', password='pass12345')
    def test_owned_boardgames_shown_in_results(self):
        r = self.client.get(reverse('accounts:profile_search'), {'owned': 'gloom'})
        self.assertContains(r, 'Gloomhaven')
    def test_filter_by_owned_boardgame(self):
        r = self.client.get(reverse('accounts:profile_search'), {'owned': 'gloom'})
        self.assertContains(r, 'alice')
        self.assertNotContains(r, 'bob')
    def test_search_by_name(self):
        r = self.client.get(reverse('accounts:profile_search'), {'q': 'ali'})
        self.assertContains(r, 'alice')
        self.assertNotContains(r, 'bob')

    def test_filter_by_genre(self):
        r = self.client.get(reverse('accounts:profile_search'), {'genre': 'party'})
        self.assertContains(r, 'bob')
        self.assertNotContains(r, 'alice')

    def test_filter_by_known_boardgame(self):
        r = self.client.get(reverse('accounts:profile_search'), {'known': 'chess'})
        self.assertContains(r, 'alice')
        self.assertNotContains(r, 'bob')

    def test_deactivated_profile_not_in_search(self):
        r = self.client.get(reverse('accounts:profile_search'))
        self.assertNotContains(r, 'dave')

    def test_deactivated_profile_detail_is_404(self):
        r = self.client.get(reverse('accounts:profile_detail', args=['dave']))
        self.assertEqual(r.status_code, 404)

    def test_profile_detail_loads(self):
        r = self.client.get(reverse('accounts:profile_detail', args=['alice']))
        self.assertEqual(r.status_code, 200)

    def test_search_requires_login(self):
        self.client.logout()
        r = self.client.get(reverse('accounts:profile_search'))
        self.assertEqual(r.status_code, 302)

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

    def test_profile_page_has_edit_profile_link(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit profile')
        self.assertContains(response, reverse('accounts:profile_editing'))

    def test_profile_page_is_read_only(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:profile'), {'display_name': 'Hacked'})
        self.assertEqual(response.status_code, 405)

    def test_editing_page_requires_login(self):
        response = self.client.get(reverse('accounts:profile_editing'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(settings.LOGIN_URL))

    def test_editing_page_renders_form_with_current_values(self):
        self.user.favorite_boardgame = 'Azul'
        self.user.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:profile_editing'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/profile_editing.html')
        self.assertIsInstance(response.context['form'], ProfileForm)
        self.assertContains(response, 'value="Azul"')

    def test_invalid_edit_rerenders_with_errors_and_does_not_save(self):
        User.objects.create_user(username='bob', email='bob@example.com', password='secret123')
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('accounts:profile_editing'),
            {'display_name': 'Alice', 'email': 'bob@example.com'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/profile_editing.html')
        self.assertIn('email', response.context['form'].errors)
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, '')

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
            reverse('accounts:profile_editing'),
            {
                'display_name': 'Alice',
                'favorite_boardgame': 'Catan',
                'favorite_genre': 'strategy',
                'known_boardgames': 'Catan, Ticket to Ride',
                'bio': 'Hello world',
                'profile_picture': uploaded,
            },
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


class RegisterViewTest(TestCase):
    def test_get_renders_form(self):
        response = self.client.get(reverse('accounts:register'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/register.html')

    def test_valid_post_creates_user_and_logs_them_in(self):
        response = self.client.post(
            reverse('accounts:register'),
            {
                'username': 'bob',
                'email': 'bob@example.com',
                'password1': 'a-str0ng-passw0rd',
                'password2': 'a-str0ng-passw0rd',
            },
        )
        self.assertRedirects(response, reverse('accounts:profile'))
        self.assertEqual(User.objects.get(username='bob').email, 'bob@example.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), User.objects.get(username='bob').pk)

    def test_duplicate_username_is_rejected_case_insensitively(self):
        User.objects.create_user(username='alice', password='secret123')
        response = self.client.post(
            reverse('accounts:register'),
            {
                'username': 'ALICE',
                'email': 'other@example.com',
                'password1': 'a-str0ng-passw0rd',
                'password2': 'a-str0ng-passw0rd',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'username', 'A user with that username already exists.'
        )
        self.assertEqual(User.objects.count(), 1)


    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user(username='alice', email='dup@example.com', password='secret123')
        response = self.client.post(
            reverse('accounts:register'),
            {
                'username': 'bob',
                'email': 'DUP@example.com',
                'password1': 'a-str0ng-passw0rd',
                'password2': 'a-str0ng-passw0rd',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'email', 'A user with that email already exists.')
        self.assertEqual(User.objects.count(), 1)

    def test_authenticated_user_is_sent_to_profile(self):
        self.client.force_login(User.objects.create_user(username='alice', password='secret123'))
        self.assertRedirects(self.client.get(reverse('accounts:register')), reverse('accounts:profile'))


class LoginLogoutViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='secret123')

    def test_login_success_redirects_to_login_redirect_url(self):
        response = self.client.post(
            reverse('accounts:login'), {'username': 'alice', 'password': 'secret123'}
        )
        self.assertRedirects(response, reverse('accounts:profile'))

    def test_login_honors_safe_next_parameter(self):
        target = reverse('accounts:profile_settings')
        response = self.client.post(
            reverse('accounts:login'),
            {'username': 'alice', 'password': 'secret123', 'next': target},
        )
        self.assertRedirects(response, target)

    def test_login_honors_next_from_the_query_string(self):
        target = reverse('accounts:profile_settings')
        response = self.client.post(
            reverse('accounts:login') + '?next=' + target,
            {'username': 'alice', 'password': 'secret123'},
        )
        self.assertRedirects(response, target)

    def test_login_ignores_offsite_next_parameter(self):
        response = self.client.post(
            reverse('accounts:login'),
            {'username': 'alice', 'password': 'secret123', 'next': 'https://evil.example.com/'},
        )
        self.assertRedirects(response, reverse('accounts:profile'))

    def test_login_failure_shows_one_error_and_does_not_sign_in(self):
        response = self.client.post(
            reverse('accounts:login'), {'username': 'alice', 'password': 'wrong'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        # The form renders its own error, so the view must not flash a second one.
        self.assertEqual(len(response.context['messages']), 0)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_anonymous_post_to_logout_is_a_no_op_redirect(self):
        response = self.client.post(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('accounts:home'))

    def test_authenticated_user_is_sent_to_profile(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse('accounts:login')), reverse('accounts:profile'))

    def test_logout_rejects_get(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:logout'))
        self.assertEqual(response.status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)

    def test_logout_via_post_ends_session(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('accounts:home'))
        self.assertNotIn('_auth_user_id', self.client.session)


class ProfileSettingsViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='secret123')

    def test_anonymous_get_redirects_to_login(self):
        response = self.client.get(reverse('accounts:profile_settings'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(settings.LOGIN_URL))

    def test_authenticated_get_renders_password_form(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:profile_settings'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/profile_settings.html')
        self.assertIsInstance(response.context['form'], PasswordChangeForm)

    def test_password_change_applies_and_keeps_session(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('accounts:profile_settings'),
            {
                'old_password': 'secret123',
                'new_password1': 'a-str0ng-passw0rd',
                'new_password2': 'a-str0ng-passw0rd',
            },
        )
        self.assertRedirects(response, reverse('accounts:profile_settings'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('a-str0ng-passw0rd'))
        # update_session_auth_hash must keep the user signed in after the change.
        self.assertIn('_auth_user_id', self.client.session)


    def test_wrong_old_password_leaves_password_unchanged(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('accounts:profile_settings'),
            {
                'old_password': 'not-my-password',
                'new_password1': 'a-str0ng-passw0rd',
                'new_password2': 'a-str0ng-passw0rd',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('secret123'))


class HomeViewTest(TestCase):
    def test_home_renders_for_anonymous_visitor(self):
        response = self.client.get(reverse('accounts:home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/home.html')
