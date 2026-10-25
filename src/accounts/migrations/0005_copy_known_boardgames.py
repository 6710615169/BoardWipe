from django.db import migrations

NAME_MAX_LENGTH = 150


def copy_known_boardgames(apps, schema_editor):
    """
    Copy each user's comma-separated known_boardgames into ProfileBoardgame rows.

    The text field itself is left untouched. Historical models do not run the
    model's save(), so names are normalised here the same way. Games already on
    a profile are skipped, which also makes re-running this migration safe.
    """
    User = apps.get_model('accounts', 'User')
    ProfileBoardgame = apps.get_model('accounts', 'ProfileBoardgame')

    for user in User.objects.exclude(known_boardgames=''):
        existing = {
            name.lower() for name in
            ProfileBoardgame.objects.filter(user=user).values_list('name', flat=True)
        }
        for raw_name in user.known_boardgames.split(','):
            name = ' '.join(raw_name.split())[:NAME_MAX_LENGTH].strip()
            if not name or name.lower() in existing:
                continue
            ProfileBoardgame.objects.create(user=user, name=name, is_known=True, is_owned=False)
            existing.add(name.lower())


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_profileboardgame'),
    ]

    operations = [
        # Reverse is a no-op: the text field still holds the original data.
        migrations.RunPython(copy_known_boardgames, migrations.RunPython.noop),
    ]
