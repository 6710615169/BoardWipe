from unittest import mock

from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import override_settings
from django.urls import reverse

from accounts import game_api
from accounts.forms import BoardgameCreateForm
from accounts.models import Boardgame, ProfileBoardgame
from accounts.tests.test_boardgames import ProfileBoardgameTestCase, make_image

ENTITY = "http://www.wikidata.org/entity/"


def row(qid, label, types="board game", min=None, max=None, image=None):
    """One binding in the shape Wikidata's SPARQL endpoint returns for DETAILS_QUERY."""
    data = {
        "game": {"value": ENTITY + qid},
        "label": {"value": label},
        "types": {"value": types},
    }
    for key, value in (("min", min), ("max", max), ("image", image)):
        if value is not None:
            data[key] = {"value": str(value)}
    return data


DETAILS = [
    row(
        "Q17271",
        " The Settlers  of Catan ",
        "board game|German-style board game|card game",
        3,
        4,
        "http://commons.wikimedia.org/wiki/Special:FilePath/Catan.jpg",
    ),
    row("Q1", "Pandemic", "board game|cooperative board game", 4, 2),
    row("Q2", "Catan: Seafarers", "board game|board game expansion", 3, 4),
    row("Q3", "Mystery", "", 0, 0),
    {"game": {"value": ENTITY + "Q4"}},
]


def catalog_game(
    name, min_players=2, max_players=4, genres=("strategy",), rating=None, **extra
):
    return Boardgame.objects.create(
        name=name,
        min_players=min_players,
        max_players=max_players,
        genres=Boardgame.format_genres(genres),
        rating=rating,
        **extra,
    )


class WikidataParsingTest(ProfileBoardgameTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.games = {
            game["external_id"]: game for game in game_api.parse_details(DETAILS)
        }

    def test_maps_name_players_cover_and_genres(self):
        catan = self.games["Q17271"]
        self.assertEqual(catan["name"], "The Settlers of Catan")
        self.assertEqual((catan["min_players"], catan["max_players"]), (3, 4))
        self.assertEqual(
            catan["cover_url"],
            "https://commons.wikimedia.org/wiki/Special:FilePath/Catan.jpg?width=400",
        )
        self.assertEqual(catan["genres"], ["card_game", "strategy"])
        self.assertEqual(self.games["Q1"]["genres"], ["cooperative"])

    def test_swaps_reversed_player_counts(self):
        self.assertEqual(
            (self.games["Q1"]["min_players"], self.games["Q1"]["max_players"]), (2, 4)
        )

    def test_skips_expansions_and_rows_without_a_name(self):
        self.assertEqual(set(self.games), {"Q17271", "Q1", "Q3"})

    def test_unknown_values_become_none_and_genre_other(self):
        mystery = self.games["Q3"]
        self.assertEqual((mystery["min_players"], mystery["max_players"]), (None, None))
        self.assertEqual(mystery["cover_url"], "")
        self.assertEqual(mystery["genres"], ["other"])

    @override_settings(GAME_API_ENABLED=True)
    def test_sync_saves_games_and_skips_fresh_ones(self):
        with mock.patch.object(game_api, "_sparql", return_value=DETAILS) as sparql:
            game_api.sync_games(["Q17271", "Q1", "Q3"])
            # Fresh rows are not fetched again.
            game_api.sync_games(["Q17271", "Q1", "Q3"])
        self.assertEqual(sparql.call_count, 1)
        self.assertIn("wd:Q17271 wd:Q1 wd:Q3", sparql.call_args.args[0])
        catan = Boardgame.objects.get(external_id="Q17271")
        self.assertEqual(catan.genres, ",card_game,strategy,")
        self.assertIsNone(catan.rating)
        # The expansion in the response is not saved.
        self.assertEqual(Boardgame.objects.count(), 3)

    def test_search_keeps_only_item_ids_and_is_cached(self):
        response = {
            "query": {
                "search": [
                    {"title": "Q17271"},
                    {"title": "Property:P1"},
                    {"title": "Q1"},
                ]
            }
        }
        with mock.patch.object(game_api, "_get_json", return_value=response) as get:
            self.assertEqual(game_api.search_ids("Catan"), ["Q17271", "Q1"])
            self.assertEqual(game_api.search_ids("catan"), ["Q17271", "Q1"])
        self.assertEqual(get.call_count, 1)
        self.assertIn("haswbstatement:P31=Q131436", get.call_args.args[1]["srsearch"])

    def test_failure_pauses_requests(self):
        with mock.patch(
            "urllib.request.urlopen", side_effect=OSError("down")
        ) as urlopen:
            for _ in range(2):
                with self.assertRaises(game_api.GameAPIError):
                    game_api.search_ids("catan")
        self.assertEqual(urlopen.call_count, 1)

    @override_settings(GAME_API_ENABLED=True)
    def test_import_games_command(self):
        with mock.patch.object(
            game_api, "popular_ids", return_value=["Q17271", "Q1"]
        ) as popular, mock.patch.object(game_api, "_sparql", return_value=DETAILS):
            call_command("import_games", limit=2, stdout=mock.MagicMock())
        popular.assert_called_once_with(2)
        self.assertTrue(Boardgame.objects.filter(external_id="Q17271").exists())
        with mock.patch.object(
            game_api, "popular_ids", side_effect=game_api.GameAPIError("down")
        ), self.assertRaises(CommandError):
            call_command("import_games")

    def test_import_games_command_needs_the_api(self):
        with self.assertRaises(CommandError):
            call_command("import_games")


class CatalogViewTest(ProfileBoardgameTestCase):
    url = reverse("accounts:boardgame_add")

    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)
        self.solo = catalog_game("Solo Quest", 1, 1, ("rpg",), rating=6.0)
        self.duel = catalog_game("Duel Cards", 2, 2, ("card_game",), rating=7.5)
        self.family = catalog_game(
            "Family Farm", 1, 4, ("family", "strategy"), rating=8.1
        )
        self.party = catalog_game("Party Words", 4, 10, ("party",), rating=None)

    def names(self, response):
        return [game.name for game in response.context["page"]]

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_sorted_by_rating_high_to_low_by_default_unrated_last(self):
        response = self.client.get(self.url)
        self.assertEqual(
            self.names(response),
            ["Family Farm", "Duel Cards", "Solo Quest", "Party Words"],
        )

    def test_can_sort_low_to_high_and_by_name(self):
        response = self.client.get(self.url, {"sort": "rating_asc"})
        self.assertEqual(
            self.names(response),
            ["Solo Quest", "Duel Cards", "Family Farm", "Party Words"],
        )
        response = self.client.get(self.url, {"sort": "name"})
        self.assertEqual(
            self.names(response),
            ["Duel Cards", "Family Farm", "Party Words", "Solo Quest"],
        )

    def test_search_by_name(self):
        response = self.client.get(self.url, {"q": "farm"})
        self.assertEqual(self.names(response), ["Family Farm"])

    def test_filter_by_genre(self):
        response = self.client.get(self.url, {"genre": "strategy"})
        self.assertEqual(self.names(response), ["Family Farm"])

    def test_filter_by_number_of_players(self):
        expected = {
            "single": ["Family Farm", "Solo Quest"],
            "two": ["Family Farm", "Duel Cards"],
            "up_to_4": ["Family Farm", "Duel Cards", "Solo Quest"],
            "five_plus": ["Party Words"],
        }
        for players, names in expected.items():
            with self.subTest(players=players):
                self.assertEqual(
                    self.names(self.client.get(self.url, {"players": players})), names
                )

    def test_shows_cover_name_players_genre_and_add_buttons(self):
        catalog_game("Covered", cover_url="https://cf.geekdo-images.com/x.jpg")
        response = self.client.get(self.url)
        self.assertContains(response, "https://cf.geekdo-images.com/x.jpg")
        self.assertContains(response, "1-4 players")
        self.assertContains(response, "Card Game")
        self.assertContains(
            response, reverse("accounts:boardgame_pick", args=[self.duel.pk])
        )
        self.assertContains(response, reverse("accounts:boardgame_create"))

    def test_games_already_on_profile_show_as_added(self):
        ProfileBoardgame.objects.create(user=self.alice, name="duel cards")
        response = self.client.get(self.url)
        self.assertNotContains(
            response, reverse("accounts:boardgame_pick", args=[self.duel.pk])
        )
        self.assertContains(response, "Added")

    def test_no_import_notice_when_the_api_is_off(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Wikidata search is turned off")


@override_settings(GAME_API_ENABLED=True)
class CatalogWikidataViewTest(ProfileBoardgameTestCase):
    url = reverse("accounts:boardgame_add")

    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)

    def test_includes_alternate_title_matches(self):
        alt = catalog_game("Die Siedler", external_id="Q17271")
        catalog_game("Unrelated")
        with mock.patch.object(game_api, "load_games", return_value=["Q17271"]) as load:
            response = self.client.get(self.url, {"q": "catan"})
        load.assert_called_once_with("catan")
        self.assertEqual(list(response.context["page"]), [alt])

    def test_blank_search_loads_the_popular_list(self):
        with mock.patch.object(game_api, "load_games", return_value=[]) as load:
            self.client.get(self.url)
        load.assert_called_once_with("")

    def test_outage_shows_saved_games(self):
        catalog_game("Family Farm")
        with mock.patch.object(
            game_api, "load_games", side_effect=game_api.GameAPIError("down")
        ), self.assertLogs("accounts.views", "WARNING"):
            response = self.client.get(self.url, {"q": "farm"})
        self.assertEqual(
            [game.name for game in response.context["page"]], ["Family Farm"]
        )
        self.assertTrue(response.context["api_unavailable"])
        self.assertContains(response, "Wikidata is not responding")


class PickBoardgameViewTest(ProfileBoardgameTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)
        self.game = catalog_game("Family Farm")
        self.url = reverse("accounts:boardgame_pick", args=[self.game.pk])

    def test_rejects_get(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_adds_game_to_profile_and_returns_to_search(self):
        back = reverse("accounts:boardgame_add") + "?q=farm"
        response = self.client.post(self.url, {"next": back})
        self.assertRedirects(response, back)
        entry = ProfileBoardgame.objects.get(user=self.alice)
        self.assertEqual(
            (entry.name, entry.boardgame, entry.is_known),
            ("Family Farm", self.game, True),
        )

    def test_adding_twice_keeps_one_entry(self):
        self.client.post(self.url)
        self.client.post(self.url)
        self.assertEqual(ProfileBoardgame.objects.filter(user=self.alice).count(), 1)

    def test_ignores_offsite_next(self):
        response = self.client.post(self.url, {"next": "https://evil.example/"})
        self.assertRedirects(response, reverse("accounts:boardgame_add"))


class CreateBoardgameTest(ProfileBoardgameTestCase):
    url = reverse("accounts:boardgame_create")

    def data(self, **overrides):
        data = {
            "name": " My  Game ",
            "min_players": 2,
            "max_players": 5,
            "genre_choices": ["party", "family"],
            "cover": make_image(),
        }
        data.update(overrides)
        return data

    def test_creates_catalog_game_and_adds_it_to_profile(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.url, self.data())
        self.assertRedirects(response, reverse("accounts:profile_editing"))
        game = Boardgame.objects.get()
        self.assertEqual(game.name, "My Game")
        self.assertEqual(game.genre_keys, ["party", "family"])
        self.assertEqual(game.created_by, self.alice)
        self.assertTrue(game.cover)
        entry = ProfileBoardgame.objects.get(user=self.alice)
        self.assertEqual(entry.boardgame, game)
        self.assertEqual(entry.picture_src, game.cover.url)

    def test_every_field_is_required(self):
        form = BoardgameCreateForm({}, {}, user=self.alice)
        self.assertFalse(form.is_valid())
        self.assertEqual(
            set(form.errors),
            {"name", "cover", "min_players", "max_players", "genre_choices"},
        )

    def test_max_players_cannot_be_below_min(self):
        data = self.data(min_players=5, max_players=2)
        form = BoardgameCreateForm(data, {"cover": data.pop("cover")}, user=self.alice)
        self.assertIn("max_players", form.errors)

    def test_rejects_zero_players(self):
        data = self.data(min_players=0)
        form = BoardgameCreateForm(data, {"cover": data.pop("cover")}, user=self.alice)
        self.assertIn("min_players", form.errors)

    def test_rejects_a_game_already_on_the_profile(self):
        ProfileBoardgame.objects.create(user=self.alice, name="my game")
        data = self.data()
        form = BoardgameCreateForm(data, {"cover": data.pop("cover")}, user=self.alice)
        self.assertIn("name", form.errors)

    def test_rejects_non_image_cover(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        data = self.data()
        data.pop("cover")
        form = BoardgameCreateForm(
            data,
            {
                "cover": SimpleUploadedFile(
                    "x.png", b"not an image", content_type="image/png"
                )
            },
            user=self.alice,
        )
        self.assertIn("cover", form.errors)

    def test_new_game_appears_in_the_catalog_for_others(self):
        self.client.force_login(self.alice)
        self.client.post(self.url, self.data())
        self.client.force_login(self.bob)
        response = self.client.get(reverse("accounts:boardgame_add"), {"q": "my game"})
        self.assertEqual([game.name for game in response.context["page"]], ["My Game"])
