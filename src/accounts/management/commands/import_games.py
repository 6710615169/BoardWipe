from django.core.management.base import BaseCommand, CommandError

from accounts import game_api


class Command(BaseCommand):
    help = (
        "Import the most popular board games from Wikidata into the catalog "
        "(ranked by how many Wikipedias cover them). Games already imported are "
        "refreshed, not duplicated."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="How many games to import (default 500).",
        )

    def handle(self, *args, limit, **options):
        if limit < 1:
            raise CommandError("--limit must be at least 1.")
        if not game_api.is_enabled():
            raise CommandError("GAME_API_ENABLED is off, so importing is turned off.")
        try:
            ids = game_api.popular_ids(limit)
            game_api.sync_games(ids)
        except game_api.GameAPIError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported or refreshed up to {len(ids)} games from Wikidata."
            )
        )
