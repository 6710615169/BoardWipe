from django.test import TestCase
from django.urls import reverse

from accounts.models import ProfileBoardgame, User
from chat.models import Message


class ChatTestCase(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", password="pass12345")
        self.alice = User.objects.create_user(
            "alice", password="x", display_name="Alice A"
        )
        self.stranger = User.objects.create_user("stranger", password="x")
        self.me.friends.add(self.alice)
        self.url = reverse("chat:conversation", args=["alice"])
        self.client.login(username="me", password="pass12345")


class ConversationAccessTests(ChatTestCase):
    def test_login_required(self):
        self.client.logout()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r.url)

    def test_friend_can_open_conversation(self):
        r = self.client.get(self.url)
        self.assertContains(r, "Chat with Alice A")

    def test_friendship_works_from_both_sides(self):
        self.client.logout()
        self.alice.set_password("pass12345")
        self.alice.save()
        self.client.login(username="alice", password="pass12345")
        r = self.client.get(reverse("chat:conversation", args=["me"]))
        self.assertEqual(r.status_code, 200)

    def test_non_friend_is_404(self):
        url = reverse("chat:conversation", args=["stranger"])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"body": "hi"}).status_code, 404)
        self.assertFalse(Message.objects.exists())

    def test_cannot_chat_with_self(self):
        url = reverse("chat:conversation", args=["me"])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_inactive_friend_is_404(self):
        self.alice.is_active = False
        self.alice.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_removed_friend_is_404(self):
        self.me.friends.remove(self.alice)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_friends_page_links_to_conversation(self):
        r = self.client.get(reverse("accounts:friends"))
        self.assertContains(r, self.url)


class SendMessageTests(ChatTestCase):
    def test_send_saves_message_and_redirects(self):
        r = self.client.post(self.url, {"body": "Game night on Friday?"})
        self.assertRedirects(r, self.url)
        message = Message.objects.get()
        self.assertEqual(message.sender, self.me)
        self.assertEqual(message.recipient, self.alice)
        self.assertEqual(message.body, "Game night on Friday?")

    def test_cannot_spoof_sender_or_recipient(self):
        self.client.post(
            self.url,
            {
                "body": "hi",
                "sender": self.alice.pk,
                "recipient": self.stranger.pk,
            },
        )
        message = Message.objects.get()
        self.assertEqual(message.sender, self.me)
        self.assertEqual(message.recipient, self.alice)

    def test_empty_message_is_rejected(self):
        r = self.client.post(self.url, {"body": "   "})
        self.assertContains(r, "Write a message.")
        self.assertFalse(Message.objects.exists())

    def test_too_long_message_is_rejected(self):
        r = self.client.post(self.url, {"body": "x" * 1001})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Message.objects.exists())

    def test_body_is_escaped(self):
        self.client.post(self.url, {"body": "<script>alert(1)</script>"})
        r = self.client.get(self.url)
        self.assertNotContains(r, "<script>alert(1)</script>")
        self.assertContains(r, "&lt;script&gt;alert(1)&lt;/script&gt;")


class TagBoardgameTests(ChatTestCase):
    def setUp(self):
        super().setUp()
        ProfileBoardgame.objects.create(user=self.me, name="Catan")
        ProfileBoardgame.objects.create(
            user=self.alice, name="Gloomhaven", is_known=False, is_owned=True
        )
        ProfileBoardgame.objects.create(user=self.stranger, name="Secret Hitler")

    def send(self, body):
        self.client.post(self.url, {"body": body})
        return self.client.get(self.url)

    def test_suggestions_offer_both_peoples_games_only(self):
        r = self.client.get(self.url)
        self.assertEqual(r.context["boardgame_names"], ["Catan", "Gloomhaven"])
        self.assertNotContains(r, "Secret Hitler")

    def test_same_game_on_both_profiles_is_offered_once(self):
        ProfileBoardgame.objects.create(user=self.alice, name="catan")
        r = self.client.get(self.url)
        self.assertEqual(len(r.context["boardgame_names"]), 2)

    def test_mention_is_highlighted_and_text_saved_as_typed(self):
        r = self.send("Bring @Gloomhaven on Friday?")
        self.assertEqual(Message.objects.get().body, "Bring @Gloomhaven on Friday?")
        self.assertContains(
            r, 'Bring <span class="chat-mention">@Gloomhaven</span> on Friday?'
        )

    def test_message_can_mention_several_games(self):
        r = self.send("@Catan or @Gloomhaven?")
        self.assertContains(
            r,
            '<span class="chat-mention">@Catan</span> or '
            '<span class="chat-mention">@Gloomhaven</span>?',
        )

    def test_mention_ignores_case(self):
        self.assertContains(
            self.send("@catan please"), '<span class="chat-mention">@catan</span>'
        )

    def test_longest_name_wins(self):
        ProfileBoardgame.objects.create(user=self.me, name="Ticket")
        ProfileBoardgame.objects.create(user=self.me, name="Ticket to Ride")
        self.assertContains(
            self.send("Play @Ticket to Ride"),
            '<span class="chat-mention">@Ticket to Ride</span>',
        )

    def test_mention_followed_by_punctuation(self):
        self.assertContains(
            self.send("Play (@Catan)?"), '(<span class="chat-mention">@Catan</span>)?'
        )

    def test_text_that_only_looks_like_a_mention_is_not_highlighted(self):
        for body in ["me@Catan.com", "@Catan2", "Catan", "@Unknown game"]:
            with self.subTest(body=body):
                Message.objects.all().delete()
                self.assertNotContains(self.send(body), '<span class="chat-mention">')

    def test_game_outside_the_conversation_is_not_highlighted(self):
        self.assertNotContains(
            self.send("@Secret Hitler"), '<span class="chat-mention">'
        )

    def test_no_games_at_all_still_shows_escaped_text(self):
        ProfileBoardgame.objects.all().delete()
        r = self.send("<b>@Catan</b>")
        self.assertContains(r, "&lt;b&gt;@Catan&lt;/b&gt;")
        self.assertNotContains(r, '<span class="chat-mention">')

    def test_highlight_stays_while_either_person_has_the_game(self):
        ProfileBoardgame.objects.create(user=self.alice, name="Catan")
        self.send("@Catan")
        ProfileBoardgame.objects.filter(user=self.me, name="Catan").delete()
        self.assertContains(
            self.client.get(self.url), '<span class="chat-mention">@Catan</span>'
        )

    def test_highlight_goes_when_nobody_has_the_game(self):
        self.send("@Catan")
        ProfileBoardgame.objects.filter(name="Catan").delete()
        r = self.client.get(self.url)
        self.assertContains(r, "@Catan")
        self.assertNotContains(r, '<span class="chat-mention">')

    def test_polled_messages_are_highlighted(self):
        Message.objects.create(sender=self.alice, recipient=self.me, body="@Catan?")
        r = self.client.get(reverse("chat:new_messages", args=["alice", 0]))
        self.assertContains(r, '<span class="chat-mention">@Catan</span>?')

    def test_game_name_and_surrounding_text_are_escaped(self):
        ProfileBoardgame.objects.create(user=self.me, name="<b>Risk</b>")
        r = self.send("<i>x</i> @<b>Risk</b>")
        self.assertContains(
            r,
            "&lt;i&gt;x&lt;/i&gt; "
            '<span class="chat-mention">@&lt;b&gt;Risk&lt;/b&gt;</span>',
        )
        self.assertNotContains(r, "<b>Risk</b>")

    def test_line_breaks_are_kept_around_mentions(self):
        self.assertContains(
            self.send("first\n@Catan"),
            'first<br><span class="chat-mention">@Catan</span>',
        )


class MessageHistoryTests(ChatTestCase):
    def test_history_shows_both_directions_in_order(self):
        Message.objects.create(
            sender=self.me, recipient=self.alice, body="first-message"
        )
        Message.objects.create(
            sender=self.alice, recipient=self.me, body="second-message"
        )
        content = self.client.get(self.url).content.decode()
        self.assertLess(content.index("first-message"), content.index("second-message"))

    def test_history_excludes_other_conversations(self):
        self.me.friends.add(self.stranger)
        Message.objects.create(
            sender=self.me, recipient=self.stranger, body="to-someone-else"
        )
        Message.objects.create(
            sender=self.stranger, recipient=self.alice, body="not-my-business"
        )
        r = self.client.get(self.url)
        self.assertNotContains(r, "to-someone-else")
        self.assertNotContains(r, "not-my-business")

    def test_history_returns_after_refriending(self):
        Message.objects.create(sender=self.me, recipient=self.alice, body="old-message")
        self.me.friends.remove(self.alice)
        self.me.friends.add(self.alice)
        self.assertContains(self.client.get(self.url), "old-message")


class NewMessagesTests(ChatTestCase):
    def poll_url(self, after_id, username="alice"):
        return reverse("chat:new_messages", args=[username, after_id])

    def test_returns_only_newer_messages(self):
        old = Message.objects.create(
            sender=self.alice, recipient=self.me, body="old-message"
        )
        Message.objects.create(sender=self.alice, recipient=self.me, body="new-message")
        r = self.client.get(self.poll_url(old.pk))
        self.assertContains(r, "new-message")
        self.assertNotContains(r, "old-message")

    def test_blank_when_nothing_new(self):
        message = Message.objects.create(
            sender=self.alice, recipient=self.me, body="hi"
        )
        r = self.client.get(self.poll_url(message.pk))
        self.assertEqual(r.content.decode().strip(), "")

    def test_excludes_other_conversations(self):
        Message.objects.create(
            sender=self.stranger, recipient=self.me, body="from-stranger"
        )
        self.assertNotContains(self.client.get(self.poll_url(0)), "from-stranger")

    def test_non_friend_is_404(self):
        self.assertEqual(self.client.get(self.poll_url(0, "stranger")).status_code, 404)

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.poll_url(0)).status_code, 302)

    def test_post_not_allowed(self):
        self.assertEqual(self.client.post(self.poll_url(0)).status_code, 405)
