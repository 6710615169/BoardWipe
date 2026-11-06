import shutil
import tempfile
from io import BytesIO

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import ProfileBoardgameEditForm, ProfileBoardgameForm, ProfileForm
from .models import ProfileBoardgame, User

TEST_MEDIA_ROOT = tempfile.mkdtemp()


def make_image(name="game.png", color="blue"):
    image = Image.new("RGB", (10, 10), color=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ProfileBoardgameTestCase(TestCase):
    """Shared setup: two users and a throwaway MEDIA_ROOT for uploads."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="secret123")
        self.bob = User.objects.create_user(username="bob", password="secret123")


class ProfileBoardgameModelTest(ProfileBoardgameTestCase):
    def test_picture_is_an_optional_imagefield(self):
        field = ProfileBoardgame._meta.get_field("picture")
        self.assertEqual(field.__class__.__name__, "ImageField")
        self.assertTrue(field.blank)

    def test_defaults_to_known_and_not_owned(self):
        game = ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        self.assertTrue(game.is_known)
        self.assertFalse(game.is_owned)

    def test_name_is_trimmed_and_inner_spaces_collapsed(self):
        game = ProfileBoardgame.objects.create(
            user=self.alice, name="  Ticket   to  Ride "
        )
        self.assertEqual(game.name, "Ticket to Ride")

    def test_user_cannot_have_the_same_game_twice_ignoring_case_and_spacing(self):
        ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProfileBoardgame.objects.create(user=self.alice, name=" CATAN ")

    def test_different_users_can_each_have_their_own_picture_of_a_game(self):
        alice_game = ProfileBoardgame.objects.create(
            user=self.alice,
            name="Catan",
            picture=make_image("alice.png"),
        )
        bob_game = ProfileBoardgame.objects.create(
            user=self.bob,
            name="Catan",
            picture=make_image("bob.png", color="red"),
        )
        self.assertNotEqual(alice_game.picture.name, bob_game.picture.name)

    def test_game_must_be_known_or_owned(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProfileBoardgame.objects.create(
                user=self.alice,
                name="Catan",
                is_known=False,
                is_owned=False,
            )

    def test_owned_but_not_known_is_allowed(self):
        game = ProfileBoardgame.objects.create(
            user=self.alice,
            name="Gloomhaven",
            is_known=False,
            is_owned=True,
        )
        self.assertTrue(game.pk)

    def test_deleting_a_user_removes_their_games(self):
        ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        self.alice.delete()
        self.assertFalse(ProfileBoardgame.objects.exists())


class ProfileBoardgameFormTest(ProfileBoardgameTestCase):
    def test_creates_game_with_picture_and_flags(self):
        form = ProfileBoardgameForm(
            {"name": "Catan", "is_known": "on", "is_owned": "on"},
            {"picture": make_image()},
            user=self.alice,
        )
        self.assertTrue(form.is_valid(), form.errors)
        game = form.save()
        self.assertEqual(game.user, self.alice)
        self.assertEqual(game.name, "Catan")
        self.assertTrue(game.is_known)
        self.assertTrue(game.is_owned)
        self.assertTrue(game.picture.name.startswith("boardgame_pictures/"))

    def test_known_is_ticked_and_owned_unticked_by_default(self):
        form = ProfileBoardgameForm(user=self.alice)
        self.assertTrue(form["is_known"].value())
        self.assertFalse(form["is_owned"].value())

    def test_picture_is_optional(self):
        form = ProfileBoardgameForm(
            {"name": "Chess", "is_known": "on"}, user=self.alice
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.save().picture)

    def test_same_user_cannot_add_the_same_game_again(self):
        ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        form = ProfileBoardgameForm(
            {"name": " cAtAn ", "is_owned": "on"},
            {"picture": make_image()},
            user=self.alice,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_another_user_can_add_a_game_someone_already_has(self):
        ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        form = ProfileBoardgameForm({"name": "Catan", "is_known": "on"}, user=self.bob)
        self.assertTrue(form.is_valid(), form.errors)

    def test_neither_known_nor_owned_is_rejected(self):
        form = ProfileBoardgameForm({"name": "Catan"}, user=self.alice)
        self.assertFalse(form.is_valid())
        self.assertIn("is_known", form.errors)

    def test_blank_name_is_rejected(self):
        form = ProfileBoardgameForm({"name": "   ", "is_known": "on"}, user=self.alice)
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_non_image_upload_is_rejected(self):
        not_an_image = SimpleUploadedFile(
            "game.png", b"not an image", content_type="image/png"
        )
        form = ProfileBoardgameForm(
            {"name": "Catan", "is_known": "on"},
            {"picture": not_an_image},
            user=self.alice,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("picture", form.errors)


class ProfileBoardgameEditFormTest(ProfileBoardgameTestCase):
    def test_cannot_rename_the_game(self):
        # Renaming would let a user dodge the one-row-per-game rule.
        self.assertEqual(
            sorted(ProfileBoardgameEditForm().fields),
            ["is_known", "is_owned", "picture"],
        )

    def test_unticking_both_flags_is_rejected(self):
        game = ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        form = ProfileBoardgameEditForm({}, instance=game)
        self.assertFalse(form.is_valid())
        self.assertIn("is_known", form.errors)
        # Only the readable message, not Django's raw "Constraint ... is violated".
        self.assertFalse(form.non_field_errors())


class ProfileFormWithoutKnownBoardgamesTest(ProfileBoardgameTestCase):
    def test_known_boardgames_text_box_is_gone_from_the_form(self):
        self.assertNotIn("known_boardgames", ProfileForm().fields)


class AddProfileBoardgameViewTest(ProfileBoardgameTestCase):
    url_name = "accounts:boardgame_add"

    def test_requires_login(self):
        response = self.client.get(reverse(self.url_name))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_get_renders_form(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse(self.url_name))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/boardgame_add.html")
        self.assertIsInstance(response.context["form"], ProfileBoardgameForm)

    def test_valid_post_adds_game_and_redirects_to_profile(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse(self.url_name),
            {
                "name": "Catan",
                "is_known": "on",
                "is_owned": "on",
                "picture": make_image(),
            },
        )
        self.assertRedirects(response, reverse("accounts:profile_editing"))
        game = ProfileBoardgame.objects.get(user=self.alice)
        self.assertEqual(game.name, "Catan")
        self.assertTrue(game.is_owned)
        self.assertTrue(game.picture)

    def test_duplicate_post_rerenders_with_error_and_saves_nothing(self):
        ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse(self.url_name),
            {"name": "CATAN", "is_known": "on", "picture": make_image()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("name", response.context["form"].errors)
        self.assertEqual(ProfileBoardgame.objects.filter(user=self.alice).count(), 1)


class EditProfileBoardgameViewTest(ProfileBoardgameTestCase):
    def setUp(self):
        super().setUp()
        self.game = ProfileBoardgame.objects.create(
            user=self.alice,
            name="Catan",
            picture=make_image("old.png"),
        )
        self.url = reverse("accounts:boardgame_edit", args=[self.game.pk])

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_get_renders_form(self):
        self.client.force_login(self.alice)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/boardgame_edit.html")
        self.assertIsInstance(response.context["form"], ProfileBoardgameEditForm)

    def test_cannot_edit_another_users_game(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        response = self.client.post(
            self.url, {"is_owned": "on", "picture": make_image("hijack.png")}
        )
        self.assertEqual(response.status_code, 404)

    def test_updates_flags(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.url, {"is_owned": "on"})
        self.assertRedirects(response, reverse("accounts:profile_editing"))
        self.game.refresh_from_db()
        self.assertFalse(self.game.is_known)
        self.assertTrue(self.game.is_owned)

    def test_replacing_picture_deletes_the_old_file(self):
        old_name = self.game.picture.name
        self.client.force_login(self.alice)
        response = self.client.post(
            self.url,
            {"is_known": "on", "picture": make_image("new.png", color="green")},
        )
        self.assertRedirects(response, reverse("accounts:profile_editing"))
        self.game.refresh_from_db()
        self.assertIn("new", self.game.picture.name)
        self.assertFalse(default_storage.exists(old_name))

    def test_clearing_picture_deletes_the_file(self):
        old_name = self.game.picture.name
        self.client.force_login(self.alice)
        self.client.post(self.url, {"is_known": "on", "picture-clear": "on"})
        self.game.refresh_from_db()
        self.assertFalse(self.game.picture)
        self.assertFalse(default_storage.exists(old_name))


class DeleteProfileBoardgameViewTest(ProfileBoardgameTestCase):
    def setUp(self):
        super().setUp()
        self.game = ProfileBoardgame.objects.create(
            user=self.alice,
            name="Catan",
            picture=make_image(),
        )
        self.url = reverse("accounts:boardgame_delete", args=[self.game.pk])

    def test_requires_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_rejects_get(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertTrue(ProfileBoardgame.objects.filter(pk=self.game.pk).exists())

    def test_cannot_delete_another_users_game(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertTrue(ProfileBoardgame.objects.filter(pk=self.game.pk).exists())

    def test_removes_game_and_its_picture_file(self):
        picture_name = self.game.picture.name
        self.client.force_login(self.alice)
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("accounts:profile_editing"))
        self.assertFalse(ProfileBoardgame.objects.filter(pk=self.game.pk).exists())
        self.assertFalse(default_storage.exists(picture_name))


class ProfileShowsBoardgamesTest(ProfileBoardgameTestCase):
    def test_lists_own_games_with_picture_or_placeholder(self):
        with_picture = ProfileBoardgame.objects.create(
            user=self.alice,
            name="Catan",
            picture=make_image(),
        )
        ProfileBoardgame.objects.create(user=self.alice, name="Azul")
        self.client.force_login(self.alice)
        response = self.client.get(reverse("accounts:profile"))

        self.assertEqual(len(response.context["profile_boardgames"]), 2)
        self.assertContains(response, "My boardgames")
        self.assertContains(response, with_picture.picture.url)
        self.assertContains(response, "Catan")
        self.assertContains(response, "Azul")
        self.assertContains(response, "game-placeholder")

    def test_lists_known_and_owned_games(self):
        ProfileBoardgame.objects.create(user=self.alice, name="Catan", is_known=True)
        ProfileBoardgame.objects.create(
            user=self.alice,
            name="Gloomhaven",
            is_known=False,
            is_owned=True,
        )
        self.client.force_login(self.alice)
        response = self.client.get(reverse("accounts:profile"))

        self.assertEqual(len(response.context["profile_boardgames"]), 2)
        self.assertContains(response, "Catan")
        self.assertContains(response, "Gloomhaven")
        self.assertContains(response, "game-badge owned")

    def test_does_not_show_other_users_games(self):
        ProfileBoardgame.objects.create(user=self.bob, name="Gloomhaven")
        self.client.force_login(self.alice)
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(len(response.context["profile_boardgames"]), 0)
        self.assertNotContains(response, "Gloomhaven")

    def test_unticking_known_keeps_an_owned_game_on_the_profile(self):
        game = ProfileBoardgame.objects.create(
            user=self.alice,
            name="Catan",
            is_known=True,
            is_owned=True,
        )
        self.client.force_login(self.alice)
        self.client.post(
            reverse("accounts:boardgame_edit", args=[game.pk]),
            {"is_owned": "on"},
        )
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(list(response.context["profile_boardgames"]), [game])
        self.assertNotContains(
            response, '<span class="game-badge">Known</span>', html=False
        )

    def test_profile_is_display_only(self):
        game = ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        self.client.force_login(self.alice)
        response = self.client.get(reverse("accounts:profile"))
        self.assertNotContains(response, reverse("accounts:boardgame_add"))
        self.assertNotContains(
            response, reverse("accounts:boardgame_edit", args=[game.pk])
        )
        self.assertNotContains(
            response, reverse("accounts:boardgame_delete", args=[game.pk])
        )


class EditProfileManagesBoardgamesTest(ProfileBoardgameTestCase):
    def test_lists_own_games_with_add_edit_and_delete(self):
        game = ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        ProfileBoardgame.objects.create(user=self.bob, name="Gloomhaven")
        self.client.force_login(self.alice)
        response = self.client.get(reverse("accounts:profile_editing"))

        self.assertEqual(list(response.context["profile_boardgames"]), [game])
        self.assertContains(response, "Your boardgames")
        self.assertNotContains(response, "Gloomhaven")
        self.assertContains(response, reverse("accounts:boardgame_add"))
        self.assertContains(
            response, reverse("accounts:boardgame_edit", args=[game.pk])
        )
        self.assertContains(
            response, reverse("accounts:boardgame_delete", args=[game.pk])
        )

    def test_add_link_shows_with_no_games(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("accounts:profile_editing"))
        self.assertContains(response, reverse("accounts:boardgame_add"))

    def test_add_and_edit_pages_link_back_to_edit_profile(self):
        game = ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        self.client.force_login(self.alice)
        for url in (
            reverse("accounts:boardgame_add"),
            reverse("accounts:boardgame_edit", args=[game.pk]),
        ):
            self.assertContains(
                self.client.get(url), reverse("accounts:profile_editing")
            )
