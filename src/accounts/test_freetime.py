from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import FreeTimeForm
from .models import FreeTime


class FreeTimeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner")
        self.other = User.objects.create_user(username="other")

        self.slot = FreeTime.objects.create(
            user=self.owner,
            date=date(2026, 11, 18),
            start_time=time(13, 0),
            end_time=time(15, 0),
        )

        self.data = {
            "date": "2026-11-18",
            "start_time": "14:00",
            "end_time": "16:00",
        }

        self.add_url = reverse("accounts:freetime_add")
        self.edit_url = reverse(
            "accounts:freetime_edit",
            kwargs={"pk": self.slot.pk},
        )

    def test_owner_can_open_forms(self):
        self.client.force_login(self.owner)

        for url in [self.add_url, self.edit_url]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(
                    response, "accounts/freetime_form.html"
                )

    def test_add_assigns_logged_in_owner(self):
        self.client.force_login(self.owner)
        data = {**self.data, "user": self.other.pk}

        response = self.client.post(self.add_url, data)

        self.assertRedirects(response, reverse("accounts:profile"))
        created = FreeTime.objects.exclude(pk=self.slot.pk).get()
        self.assertEqual(created.user, self.owner)
        self.assertEqual(created.start_time, time(14, 0))

    def test_owner_can_edit(self):
        self.client.force_login(self.owner)

        response = self.client.post(self.edit_url, self.data)

        self.assertRedirects(response, reverse("accounts:profile"))
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.start_time, time(14, 0))
        self.assertEqual(self.slot.end_time, time(16, 0))
        self.assertEqual(self.slot.user, self.owner)

    def test_invalid_time_ranges_are_rejected(self):
        self.client.force_login(self.owner)

        for end_time in ["13:00", "14:00"]:
            data = {**self.data, "end_time": end_time}

            with self.subTest(end_time=end_time):
                form = FreeTimeForm(data=data)
                self.assertFalse(form.is_valid())
                self.assertIn("end_time", form.errors)

                for url in [self.add_url, self.edit_url]:
                    response = self.client.post(url, data)
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(
                        response, "End time must be after start time."
                    )

        self.assertEqual(FreeTime.objects.count(), 1)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.start_time, time(13, 0))
        self.assertEqual(self.slot.end_time, time(15, 0))

    def test_other_user_cannot_edit(self):
        self.client.force_login(self.other)

        self.assertEqual(
            self.client.get(self.edit_url).status_code, 404
        )
        self.assertEqual(
            self.client.post(self.edit_url, self.data).status_code, 404
        )

        self.slot.refresh_from_db()
        self.assertEqual(self.slot.start_time, time(13, 0))
        self.assertEqual(self.slot.end_time, time(15, 0))

    def test_calendar_visible_on_both_profiles(self):
        cases = [
            (self.owner, reverse("accounts:profile")),
            (
                self.other,
                reverse(
                    "accounts:profile_detail",
                    kwargs={"username": self.owner.username},
                ),
            ),
        ]

        for viewer, url in cases:
            with self.subTest(viewer=viewer.username):
                self.client.force_login(viewer)
                response = self.client.get(url, {"month": "2026-11"})

                self.assertEqual(response.status_code, 200)
                shown_slots = [
                    slot
                    for week in response.context["calendar_weeks"]
                    for cell in week
                    for slot in cell["slots"]
                ]
                self.assertEqual(shown_slots, [self.slot])

                if viewer == self.other:
                    self.assertNotContains(response, self.edit_url)
                    self.assertNotContains(response, self.add_url)

    def test_login_required(self):
        for url in [self.add_url, self.edit_url]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("next=", response.url)