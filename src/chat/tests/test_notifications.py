from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import FriendRequest, User
from chat.models import ConversationNotification, Message
from chat.notifications import make_preview, notify_new_message

SITE = "https://boardwipe.example"


@override_settings(SITE_URL=SITE, NOTIFICATION_THROTTLE_MINUTES=15)
class NotificationTestCase(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", email="me@x.com", password="pass12345")
        self.alice = User.objects.create_user(
            "alice", email="alice@x.com", password="pass12345", display_name="Alice A"
        )
        self.me.friends.add(self.alice)
        self.client.login(username="me", password="pass12345")
        self.url = reverse("chat:conversation", args=["alice"])

    def send(self, body="hello"):
        return self.client.post(self.url, {"body": body})


class MessageEmailTests(NotificationTestCase):
    def test_recipient_gets_email_with_sender_preview_and_link(self):
        self.send("Fancy a game of Catan tonight?")
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["alice@x.com"])
        self.assertIn("me", email.subject)
        self.assertIn("Fancy a game of Catan tonight?", email.body)
        # The link goes to the conversation with the sender, as an absolute URL.
        self.assertIn(f"{SITE}/chat/me/", email.body)
        html = email.alternatives[0][0]
        self.assertIn(f'href="{SITE}/chat/me/"', html)
        self.assertIn("Fancy a game of Catan tonight?", html)

    def test_sender_gets_no_email(self):
        self.send()
        self.assertNotIn("me@x.com", [addr for m in mail.outbox for addr in m.to])

    def test_html_in_message_is_escaped_in_html_email(self):
        self.send("<script>alert(1)</script>")
        html = mail.outbox[0].alternatives[0][0]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_long_message_is_cut_to_a_preview(self):
        self.send("word " * 150)
        self.assertLessEqual(len(make_preview("word " * 150)), 140)
        self.assertNotIn("word " * 100, mail.outbox[0].body)

    def test_newline_in_display_name_cannot_break_subject(self):
        self.me.display_name = "Mallory\nBcc: x@y.com"
        self.me.save()
        self.send()
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("\n", mail.outbox[0].subject)

    def test_no_email_for_blank_address(self):
        self.alice.email = ""
        self.alice.save()
        self.send()
        self.assertEqual(mail.outbox, [])

    def test_no_email_for_inactive_recipient(self):
        # The conversation page 404s for inactive friends, so call directly.
        self.alice.is_active = False
        self.alice.save()
        msg = Message.objects.create(sender=self.me, recipient=self.alice, body="hi")
        self.assertFalse(notify_new_message(msg))
        self.assertEqual(mail.outbox, [])

    def test_invalid_message_sends_nothing(self):
        self.send("")
        self.assertEqual(mail.outbox, [])


class ThrottleTests(NotificationTestCase):
    def test_burst_of_messages_sends_one_email(self):
        for i in range(10):
            self.send(f"message {i}")
        self.assertEqual(Message.objects.count(), 10)
        self.assertEqual(len(mail.outbox), 1)

    def test_last_notified_at_is_stored(self):
        self.send()
        row = ConversationNotification.objects.get(recipient=self.alice, sender=self.me)
        self.assertLess(timezone.now() - row.last_notified_at, timedelta(minutes=1))

    def test_email_sent_again_after_window(self):
        self.send("first")
        ConversationNotification.objects.update(
            last_notified_at=timezone.now() - timedelta(minutes=16)
        )
        self.send("second")
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("second", mail.outbox[1].body)

    def test_no_email_just_inside_window(self):
        self.send("first")
        ConversationNotification.objects.update(
            last_notified_at=timezone.now() - timedelta(minutes=14)
        )
        self.send("second")
        self.assertEqual(len(mail.outbox), 1)

    def test_throttle_is_per_conversation(self):
        bob = User.objects.create_user("bob", email="bob@x.com", password="x")
        self.me.friends.add(bob)
        self.send("to alice")
        self.client.post(reverse("chat:conversation", args=["bob"]), {"body": "to bob"})
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), ["alice@x.com", "bob@x.com"]
        )

    def test_throttle_is_per_direction(self):
        self.send("hi alice")
        self.client.logout()
        self.client.login(username="alice", password="pass12345")
        self.client.post(reverse("chat:conversation", args=["me"]), {"body": "hi me"})
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(NOTIFICATION_THROTTLE_MINUTES=10)
    def test_window_is_configurable(self):
        self.send("first")
        ConversationNotification.objects.update(
            last_notified_at=timezone.now() - timedelta(minutes=11)
        )
        self.send("second")
        self.assertEqual(len(mail.outbox), 2)

    def test_failed_send_does_not_block_message_or_use_up_the_window(self):
        with mock.patch(
            "chat.notifications.EmailMultiAlternatives.send",
            side_effect=OSError("smtp down"),
        ):
            with self.assertLogs("chat.notifications", level="ERROR"):
                r = self.send("while smtp is down")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Message.objects.count(), 1)
        self.assertFalse(ConversationNotification.objects.exists())
        # SMTP recovers: the very next message is allowed to notify.
        self.send("smtp is back")
        self.assertEqual(len(mail.outbox), 1)

    def test_failed_send_restores_previous_timestamp(self):
        self.send("first")
        old = timezone.now() - timedelta(minutes=20)
        ConversationNotification.objects.update(last_notified_at=old)
        with mock.patch(
            "chat.notifications.EmailMultiAlternatives.send",
            side_effect=OSError("smtp down"),
        ):
            with self.assertLogs("chat.notifications", level="ERROR"):
                self.send("second")
        row = ConversationNotification.objects.get()
        self.assertEqual(row.last_notified_at, old)


class OptOutTests(NotificationTestCase):
    def test_default_is_opted_in(self):
        self.assertTrue(self.alice.email_notifications)

    def test_opted_out_user_gets_no_message_email(self):
        self.alice.email_notifications = False
        self.alice.save()
        self.send()
        self.assertEqual(mail.outbox, [])
        # Skipped emails must not consume the throttle window either.
        self.assertFalse(ConversationNotification.objects.exists())

    def test_opted_out_user_gets_no_friend_request_email(self):
        bob = User.objects.create_user(
            "bob", email="bob@x.com", password="x", email_notifications=False
        )
        self.client.post(reverse("accounts:send_friend_request", args=["bob"]))
        self.assertTrue(FriendRequest.objects.filter(to_user=bob).exists())
        self.assertEqual(mail.outbox, [])

    def test_settings_page_shows_toggle(self):
        r = self.client.get(reverse("accounts:profile_settings"))
        self.assertContains(r, "email_notifications")

    def test_settings_toggle_turns_emails_off_and_on(self):
        url = reverse("accounts:profile_settings")
        self.client.login(username="alice", password="pass12345")
        # Unticked checkbox sends no field at all.
        r = self.client.post(url, {"save_notifications": "1"})
        self.assertRedirects(r, url)
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.email_notifications)

        self.client.post(url, {"save_notifications": "1", "email_notifications": "on"})
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.email_notifications)

    def test_password_form_still_works_and_leaves_toggle_alone(self):
        url = reverse("accounts:profile_settings")
        r = self.client.post(
            url,
            {
                "old_password": "pass12345",
                "new_password1": "a-new-Passw0rd-xyz",
                "new_password2": "a-new-Passw0rd-xyz",
            },
        )
        self.assertRedirects(r, url)
        self.me.refresh_from_db()
        self.assertTrue(self.me.check_password("a-new-Passw0rd-xyz"))
        self.assertTrue(self.me.email_notifications)

    def test_settings_page_requires_login(self):
        self.client.logout()
        r = self.client.post(
            reverse("accounts:profile_settings"), {"save_notifications": "1"}
        )
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r.url)


class FriendRequestEmailTests(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.bob = User.objects.create_user("bob", email="bob@x.com", password="x")

    def test_friend_request_emails_recipient_with_link_to_friends_page(self):
        self.client.post(reverse("accounts:send_friend_request", args=["bob"]))
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["bob@x.com"])
        self.assertIn("me", email.subject)
        self.assertIn(f"{SITE}/profile/friends/", email.body)

    def test_repeating_the_request_does_not_email_again(self):
        url = reverse("accounts:send_friend_request", args=["bob"])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(len(mail.outbox), 1)

    def test_accepting_a_request_sends_no_email(self):
        FriendRequest.objects.create(from_user=self.bob, to_user=self.me)
        self.client.post(reverse("accounts:send_friend_request", args=["bob"]))
        self.assertEqual(mail.outbox, [])


class EmailLinkLoginRedirectTests(NotificationTestCase):
    def test_logged_out_click_goes_to_login_then_back_to_chat(self):
        self.client.logout()
        chat_path = reverse("chat:conversation", args=["me"])
        # alice clicks the link in her email without being logged in.
        r = self.client.get(chat_path)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, f"{reverse('accounts:login')}?next={chat_path}")

        # The login page keeps the target in its form...
        r = self.client.get(r.url)
        self.assertContains(r, f'name="next" value="{chat_path}"')

        # ...and a successful login lands on the conversation.
        r = self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": "pass12345", "next": chat_path},
        )
        self.assertRedirects(r, chat_path)

    def test_login_will_not_redirect_off_site(self):
        self.client.logout()
        r = self.client.post(
            reverse("accounts:login"),
            {
                "username": "alice",
                "password": "pass12345",
                "next": "https://evil.example/",
            },
        )
        self.assertRedirects(r, reverse("accounts:profile"))
