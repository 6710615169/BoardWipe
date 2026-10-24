import shutil
import tempfile
from io import BytesIO

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import AddBoardGameForm, BoardGameImageForm, ProfileForm
from .models import BoardGame, User, UserBoardGame

TEST_MEDIA_ROOT = tempfile.mkdtemp()


def make_image(name='game.png', color='blue'):
    image = Image.new('RGB', (10, 10), color=color)
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class BoardGameTestCase(TestCase):
    """Shared setup: two users and a throwaway MEDIA_ROOT for uploads."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.alice = User.objects.create_user(username='alice', password='secret123')
        self.bob = User.objects.create_user(username='bob', password='secret123')


class BoardGameModelTest(BoardGameTestCase):
    def test_name_is_trimmed_and_inner_spaces_collapsed(self):
        game = BoardGame.objects.create(name='  Ticket   to  Ride ')
        self.assertEqual(game.name, 'Ticket to Ride')

    def test_names_are_unique_case_insensitively(self):
        BoardGame.objects.create(name='Catan')
        with self.assertRaises(IntegrityError), transaction.atomic():
            BoardGame.objects.create(name='CATAN')

    def test_str_is_name(self):
        self.assertEqual(str(BoardGame.objects.create(name='Chess')), 'Chess')


class UserBoardGameModelTest(BoardGameTestCase):
    def setUp(self):
        super().setUp()
        self.catan = BoardGame.objects.create(name='Catan')

    def test_image_is_an_optional_imagefield(self):
        field = UserBoardGame._meta.get_field('image')
        self.assertEqual(field.__class__.__name__, 'ImageField')
        self.assertTrue(field.blank)

    def test_user_cannot_have_the_same_game_twice(self):
        UserBoardGame.objects.create(user=self.alice, boardgame=self.catan)
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserBoardGame.objects.create(user=self.alice, boardgame=self.catan)

    def test_each_user_keeps_their_own_picture_of_the_same_game(self):
        alice_entry = UserBoardGame.objects.create(
            user=self.alice, boardgame=self.catan, image=make_image('alice.png'),
        )
        bob_entry = UserBoardGame.objects.create(
            user=self.bob, boardgame=self.catan, image=make_image('bob.png', color='red'),
        )
        self.assertEqual(BoardGame.objects.count(), 1)
        self.assertNotEqual(alice_entry.image.name, bob_entry.image.name)

    def test_known_boardgames_relation_goes_through_user_boardgame(self):
        UserBoardGame.objects.create(user=self.alice, boardgame=self.catan)
        self.assertQuerySetEqual(self.alice.known_boardgames.all(), [self.catan])
        self.assertQuerySetEqual(self.catan.known_by.all(), [self.alice])

    def test_deleting_a_user_removes_their_entries_but_keeps_the_game(self):
        UserBoardGame.objects.create(user=self.alice, boardgame=self.catan)
        self.alice.delete()
        self.assertFalse(UserBoardGame.objects.exists())
        self.assertTrue(BoardGame.objects.filter(pk=self.catan.pk).exists())


class AddBoardGameFormTest(BoardGameTestCase):
    def test_creates_game_and_entry_with_picture(self):
        form = AddBoardGameForm({'name': 'Catan'}, {'image': make_image()}, user=self.alice)
        self.assertTrue(form.is_valid(), form.errors)
        entry = form.save()
        self.assertEqual(entry.user, self.alice)
        self.assertEqual(entry.boardgame.name, 'Catan')
        self.assertTrue(entry.image.name.startswith('boardgame_images/'))

    def test_picture_is_optional(self):
        form = AddBoardGameForm({'name': 'Chess'}, user=self.alice)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.save().image)

    def test_reuses_existing_game_regardless_of_case_and_spacing(self):
        existing = BoardGame.objects.create(name='Ticket to Ride')
        form = AddBoardGameForm({'name': '  ticket  TO ride '}, user=self.alice)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().boardgame, existing)
        self.assertEqual(BoardGame.objects.count(), 1)

    def test_same_user_cannot_add_the_same_game_again(self):
        catan = BoardGame.objects.create(name='Catan')
        UserBoardGame.objects.create(user=self.alice, boardgame=catan)
        form = AddBoardGameForm({'name': 'cAtAn '}, {'image': make_image()}, user=self.alice)
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)

    def test_another_user_can_add_a_game_someone_already_has(self):
        catan = BoardGame.objects.create(name='Catan')
        UserBoardGame.objects.create(user=self.alice, boardgame=catan)
        form = AddBoardGameForm({'name': 'Catan'}, user=self.bob)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().boardgame, catan)

    def test_blank_name_is_rejected(self):
        form = AddBoardGameForm({'name': '   '}, user=self.alice)
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)

    def test_non_image_upload_is_rejected(self):
        not_an_image = SimpleUploadedFile('game.png', b'not an image', content_type='image/png')
        form = AddBoardGameForm({'name': 'Catan'}, {'image': not_an_image}, user=self.alice)
        self.assertFalse(form.is_valid())
        self.assertIn('image', form.errors)


class BoardGameImageFormTest(BoardGameTestCase):
    def test_only_exposes_the_image(self):
        # Renaming would let a user dodge the one-entry-per-game rule, so the
        # edit form must not offer the game or the owner.
        self.assertEqual(list(BoardGameImageForm().fields), ['image'])


class ProfileFormWithoutKnownBoardgamesTest(BoardGameTestCase):
    def test_known_boardgames_text_field_is_gone(self):
        self.assertNotIn('known_boardgames', ProfileForm().fields)


class AddBoardGameViewTest(BoardGameTestCase):
    url_name = 'accounts:boardgame_add'

    def test_requires_login(self):
        response = self.client.get(reverse(self.url_name))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(settings.LOGIN_URL))

    def test_get_renders_form(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse(self.url_name))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/boardgame_add.html')
        self.assertIsInstance(response.context['form'], AddBoardGameForm)

    def test_valid_post_adds_game_and_redirects_to_profile(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse(self.url_name), {'name': 'Catan', 'image': make_image()},
        )
        self.assertRedirects(response, reverse('accounts:profile'))
        entry = UserBoardGame.objects.get(user=self.alice)
        self.assertEqual(entry.boardgame.name, 'Catan')
        self.assertTrue(entry.image)

    def test_duplicate_post_rerenders_with_error_and_saves_nothing(self):
        catan = BoardGame.objects.create(name='Catan')
        UserBoardGame.objects.create(user=self.alice, boardgame=catan)
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse(self.url_name), {'name': 'CATAN', 'image': make_image()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('name', response.context['form'].errors)
        self.assertEqual(UserBoardGame.objects.filter(user=self.alice).count(), 1)


class EditBoardGameViewTest(BoardGameTestCase):
    def setUp(self):
        super().setUp()
        self.entry = UserBoardGame.objects.create(
            user=self.alice,
            boardgame=BoardGame.objects.create(name='Catan'),
            image=make_image('old.png'),
        )
        self.url = reverse('accounts:boardgame_edit', args=[self.entry.pk])

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(settings.LOGIN_URL))

    def test_get_renders_form(self):
        self.client.force_login(self.alice)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/boardgame_edit.html')
        self.assertIsInstance(response.context['form'], BoardGameImageForm)

    def test_cannot_edit_another_users_entry(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(
            self.client.post(self.url, {'image': make_image('hijack.png')}).status_code, 404,
        )

    def test_replacing_picture_deletes_the_old_file(self):
        old_name = self.entry.image.name
        self.client.force_login(self.alice)
        response = self.client.post(self.url, {'image': make_image('new.png', color='green')})
        self.assertRedirects(response, reverse('accounts:profile'))
        self.entry.refresh_from_db()
        self.assertIn('new', self.entry.image.name)
        self.assertFalse(default_storage.exists(old_name))

    def test_clearing_picture_deletes_the_file(self):
        old_name = self.entry.image.name
        self.client.force_login(self.alice)
        self.client.post(self.url, {'image-clear': 'on'})
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.image)
        self.assertFalse(default_storage.exists(old_name))


class DeleteBoardGameViewTest(BoardGameTestCase):
    def setUp(self):
        super().setUp()
        self.catan = BoardGame.objects.create(name='Catan')
        self.entry = UserBoardGame.objects.create(
            user=self.alice, boardgame=self.catan, image=make_image(),
        )
        self.url = reverse('accounts:boardgame_delete', args=[self.entry.pk])

    def test_requires_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(settings.LOGIN_URL))

    def test_rejects_get(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertTrue(UserBoardGame.objects.filter(pk=self.entry.pk).exists())

    def test_cannot_delete_another_users_entry(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertTrue(UserBoardGame.objects.filter(pk=self.entry.pk).exists())

    def test_removes_entry_and_its_file_but_keeps_the_game(self):
        image_name = self.entry.image.name
        self.client.force_login(self.alice)
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse('accounts:profile'))
        self.assertFalse(UserBoardGame.objects.filter(pk=self.entry.pk).exists())
        self.assertFalse(default_storage.exists(image_name))
        self.assertTrue(BoardGame.objects.filter(pk=self.catan.pk).exists())


class ProfileShowsBoardGamesTest(BoardGameTestCase):
    def test_lists_own_entries_with_picture_or_placeholder(self):
        with_picture = UserBoardGame.objects.create(
            user=self.alice, boardgame=BoardGame.objects.create(name='Catan'), image=make_image(),
        )
        UserBoardGame.objects.create(user=self.alice, boardgame=BoardGame.objects.create(name='Azul'))
        self.client.force_login(self.alice)
        response = self.client.get(reverse('accounts:profile'))

        self.assertEqual(len(response.context['boardgame_entries']), 2)
        self.assertContains(response, with_picture.image.url)
        self.assertContains(response, 'Catan')
        self.assertContains(response, 'Azul')
        self.assertContains(response, 'game-placeholder')

    def test_does_not_show_other_users_games(self):
        UserBoardGame.objects.create(user=self.bob, boardgame=BoardGame.objects.create(name='Gloomhaven'))
        self.client.force_login(self.alice)
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(len(response.context['boardgame_entries']), 0)
        self.assertNotContains(response, 'Gloomhaven')

    def test_links_to_add_edit_and_delete(self):
        entry = UserBoardGame.objects.create(
            user=self.alice, boardgame=BoardGame.objects.create(name='Catan'),
        )
        self.client.force_login(self.alice)
        response = self.client.get(reverse('accounts:profile'))
        self.assertContains(response, reverse('accounts:boardgame_add'))
        self.assertContains(response, reverse('accounts:boardgame_edit', args=[entry.pk]))
        self.assertContains(response, reverse('accounts:boardgame_delete', args=[entry.pk]))
