"""
Client for Wikidata (https://www.wikidata.org), the source of the game catalog.

Wikidata is free, needs no key and is CC0-licensed. Two endpoints are used:
- the MediaWiki search API finds board/card games by name (ranked, and it also
  matches alternate titles), and
- the SPARQL query service returns each game's details: English name, player
  counts (P1872/P1873), image (P18) and the labels of its types, genres and
  mechanics (P31/P136/P4151), which are mapped onto User.GENRE_CHOICES.

Wikidata has no ratings, so imported games have rating=None. Games fetched are
copied into the local Boardgame catalog, so filtering and sorting run as normal
database queries. Wikimedia asks API clients to send a descriptive User-Agent.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import Boardgame

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.wikidata.org/w/api.php"
SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "BoardWipe/1.0 (https://github.com/6710615169/BoardWipe)"
TIMEOUT_SECONDS = 15

BOARD_GAME = "Q131436"
CARD_GAME = "Q142714"
SEARCH_LIMIT = 20
POPULAR_LIMIT = 60
# Ids per SPARQL details query, to keep the query string short.
DETAILS_BATCH_SIZE = 50
CACHE_SECONDS = 60 * 60
# Refresh a cached game's details at most this often.
REFRESH_AFTER = timedelta(days=7)
# After a failed request, skip Wikidata for this long so an outage does not
# slow down every page view.
RETRY_AFTER_SECONDS = 5 * 60
FAILED_KEY = "wikidata:failed"
COVER_WIDTH = 400

# Keyword in an English type/genre/mechanic label -> User.GENRE_CHOICES key.
GENRE_KEYWORDS = [
    ("card game", "card_game"),
    ("strategy", "strategy"),
    ("german-style", "strategy"),
    ("eurogame", "strategy"),
    ("worker placement", "strategy"),
    ("party", "party"),
    ("cooperative", "cooperative"),
    ("co-operative", "cooperative"),
    ("family", "family"),
    ("children's", "family"),
    ("wargame", "war_game"),
    ("war game", "war_game"),
    ("role-playing", "rpg"),
]

DETAILS_QUERY = """
SELECT ?game ?label (MIN(?minp) AS ?min) (MAX(?maxp) AS ?max) (SAMPLE(?img) AS ?image)
       (GROUP_CONCAT(DISTINCT ?typeLabel; separator="|") AS ?types)
WHERE {
  VALUES ?game { %s }
  ?game rdfs:label ?label. FILTER(LANG(?label) = "en")
  OPTIONAL { ?game wdt:P1872 ?minp }
  OPTIONAL { ?game wdt:P1873 ?maxp }
  OPTIONAL { ?game wdt:P18 ?img }
  OPTIONAL {
    VALUES ?prop { wdt:P31 wdt:P136 wdt:P4151 }
    ?game ?prop ?type. ?type rdfs:label ?typeLabel. FILTER(LANG(?typeLabel) = "en")
  }
}
GROUP BY ?game ?label
"""

# Board games ranked by how many Wikipedias have an article on them, a decent
# stand-in for "popular" shown before anything is searched.
POPULAR_QUERY = """
SELECT ?game WHERE { ?game wdt:P31 wd:%s; wikibase:sitelinks ?links. }
ORDER BY DESC(?links) LIMIT %d
"""


class GameAPIError(Exception):
    """Wikidata could not be reached or answered with something unusable."""


def is_enabled():
    return bool(getattr(settings, "GAME_API_ENABLED", False))


def _get_json(url, params):
    if cache.get(FAILED_KEY):
        raise GameAPIError("Wikidata failed recently; not retrying yet")
    if not url.startswith("https://"):
        raise GameAPIError(f"Refusing non-HTTPS URL: {url}")
    request = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        headers={
            "Accept": "application/json, application/sparql-results+json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        # The scheme is checked above, so file:// and similar can't get here.
        with urllib.request.urlopen(  # nosec B310
            request, timeout=TIMEOUT_SECONDS
        ) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        cache.set(FAILED_KEY, True, RETRY_AFTER_SECONDS)
        raise GameAPIError(f"Wikidata request failed: {exc}") from exc


def _sparql(query):
    data = _get_json(SPARQL_URL, {"query": query, "format": "json"})
    try:
        return data["results"]["bindings"]
    except (KeyError, TypeError) as exc:
        raise GameAPIError("Wikidata sent an unexpected SPARQL response") from exc


def _qid(uri):
    return uri.rsplit("/", 1)[-1]


def _int_or_none(text):
    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def cover_url(commons_url):
    """Turn a P18 Commons file URL into a resized https image URL."""
    if not commons_url:
        return ""
    url = commons_url.replace("http://", "https://", 1)
    return f"{url}?width={COVER_WIDTH}"


def genres_from_labels(labels):
    genres = set()
    for label in labels:
        label = label.casefold()
        for keyword, genre in GENRE_KEYWORDS:
            if keyword in label:
                genres.add(genre)
    return sorted(genres) or ["other"]


def parse_details(bindings):
    """Boardgame field values for each base game in a DETAILS_QUERY result."""
    games = []
    for row in bindings:

        def value(key):
            return (row.get(key) or {}).get("value")

        external_id = _qid(value("game") or "")
        name = " ".join((value("label") or "").split())
        types = [label for label in (value("types") or "").split("|") if label]
        if not external_id or not name:
            continue
        # Expansions need the base game, so they are not offered on their own.
        if any("expansion" in label.casefold() for label in types):
            continue
        min_players, max_players = _int_or_none(value("min")), _int_or_none(
            value("max")
        )
        if min_players and max_players and min_players > max_players:
            min_players, max_players = max_players, min_players
        games.append(
            {
                "external_id": external_id,
                "name": name[: Boardgame._meta.get_field("name").max_length],
                "cover_url": cover_url(value("image"))[
                    : Boardgame._meta.get_field("cover_url").max_length
                ],
                "min_players": min_players,
                "max_players": max_players,
                "genres": genres_from_labels(types),
            }
        )
    return games


def search_ids(query):
    """Wikidata ids of board/card games matching query, best first (cached)."""
    key = "wikidata:search:" + urllib.parse.quote(query.casefold())[:200]
    ids = cache.get(key)
    if ids is None:
        data = _get_json(
            SEARCH_URL,
            {
                "action": "query",
                "list": "search",
                "format": "json",
                "srsearch": f"{query} haswbstatement:P31={BOARD_GAME}|P31={CARD_GAME}",
                "srlimit": SEARCH_LIMIT,
                "srprop": "",
            },
        )
        try:
            hits = data["query"]["search"]
        except (KeyError, TypeError) as exc:
            raise GameAPIError("Wikidata sent an unexpected search response") from exc
        ids = [
            hit["title"] for hit in hits if str(hit.get("title", "")).startswith("Q")
        ]
        cache.set(key, ids, CACHE_SECONDS)
    return ids


def popular_ids(limit=POPULAR_LIMIT):
    """Wikidata ids of the most widely covered board games (cached)."""
    key = f"wikidata:popular:{limit}"
    ids = cache.get(key)
    if ids is None:
        ids = [
            _qid(row["game"]["value"])
            for row in _sparql(POPULAR_QUERY % (BOARD_GAME, limit))
        ]
        cache.set(key, ids, CACHE_SECONDS)
    return ids


def sync_games(ids):
    """Fetch and save details for ids missing from, or stale in, the catalog."""
    fresh_since = timezone.now() - REFRESH_AFTER
    fresh = set(
        Boardgame.objects.filter(
            external_id__in=ids, fetched_at__gte=fresh_since
        ).values_list("external_id", flat=True)
    )
    to_fetch = [qid for qid in dict.fromkeys(ids) if qid not in fresh]

    for start in range(0, len(to_fetch), DETAILS_BATCH_SIZE):
        batch = to_fetch[start : start + DETAILS_BATCH_SIZE]
        query = DETAILS_QUERY % " ".join(f"wd:{qid}" for qid in batch)
        for data in parse_details(_sparql(query)):
            data["genres"] = Boardgame.format_genres(data["genres"])
            Boardgame.objects.update_or_create(
                external_id=data.pop("external_id"),
                defaults={**data, "fetched_at": timezone.now()},
            )


def load_games(query):
    """
    Pull games matching query (or the popular list when blank) into the catalog.

    Returns the Wikidata ids found, so the caller can include them even when
    Wikidata matched on an alternate title the local name search would miss.
    Raises GameAPIError when Wikidata is unreachable.
    """
    ids = search_ids(query) if query else popular_ids()
    sync_games(ids)
    return ids
