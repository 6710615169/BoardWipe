import django.db.models.functions.text
from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def fail_on_duplicate_emails(apps, schema_editor):
    """
    Stop with a readable message if existing data would violate the new
    constraint, instead of a bare IntegrityError from the database.
    """
    User = apps.get_model("accounts", "User")
    duplicates = list(
        User.objects.exclude(email="")
        .annotate(email_lower=Lower("email"))
        .values("email_lower")
        .annotate(n=Count("pk"))
        .filter(n__gt=1)
        .values_list("email_lower", flat=True)
    )
    if duplicates:
        raise RuntimeError(
            "Cannot add the unique email constraint: these emails are used by "
            "more than one account (compared case-insensitively): "
            + ", ".join(sorted(duplicates))
            + ". Merge, change or blank the duplicates, then run migrate again."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_profile_fields"),
    ]

    operations = [
        migrations.RunPython(fail_on_duplicate_emails, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("email"),
                condition=models.Q(("email", ""), _negated=True),
                name="accounts_user_email_ci_unique_nonblank",
                violation_error_message="A user with that email already exists.",
            ),
        ),
    ]
