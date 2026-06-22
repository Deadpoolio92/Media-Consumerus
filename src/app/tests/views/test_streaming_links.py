"""Tests for the E6 add/delete streaming-link views."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Sources, StreamingLink


class AddStreamingLinkTests(TestCase):
    """POST add_streaming_link — create a user link (and its Item on demand)."""

    def setUp(self):
        """Log a user in (the views are login-gated globally)."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.detail_url = reverse(
            "media_details",
            kwargs={
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "238",
                "title": "the-godfather",
            },
        )
        self.add_url = reverse(
            "add_streaming_link",
            kwargs={
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "238",
            },
        )

    def test_adds_link_and_creates_item(self):
        """A valid POST creates the link and upserts the title's Item."""
        response = self.client.post(
            self.add_url,
            {
                "name": "Netflix",
                "url": "https://netflix.com/title/238",
                "title": "The Godfather",
                "image": "http://example.com/i.jpg",
                "next": self.detail_url,
            },
        )

        self.assertRedirects(
            response, self.detail_url, fetch_redirect_response=False
        )
        item = Item.objects.get(media_id="238", media_type=MediaTypes.MOVIE.value)
        self.assertEqual(item.title, "The Godfather")
        link = StreamingLink.objects.get(item=item)
        self.assertEqual(link.name, "Netflix")
        self.assertEqual(link.url, "https://netflix.com/title/238")

    def test_reuses_existing_item(self):
        """A link for an already-tracked title attaches to the existing Item."""
        item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Godfather",
            image="http://example.com/i.jpg",
        )
        self.client.post(
            self.add_url,
            {"name": "Hulu", "url": "https://hulu.com", "next": self.detail_url},
        )
        self.assertEqual(Item.objects.filter(media_id="238").count(), 1)
        self.assertEqual(item.streaming_links.count(), 1)

    def test_missing_fields_adds_nothing(self):
        """A missing name or url creates no link."""
        self.client.post(
            self.add_url, {"name": "", "url": "https://x", "next": self.detail_url}
        )
        self.client.post(
            self.add_url, {"name": "X", "url": "", "next": self.detail_url}
        )
        self.assertEqual(StreamingLink.objects.count(), 0)

    def test_invalid_url_adds_nothing(self):
        """A non-URL value is rejected by the field validator."""
        self.client.post(
            self.add_url,
            {"name": "Bad", "url": "not a url", "next": self.detail_url},
        )
        self.assertEqual(StreamingLink.objects.count(), 0)

    def test_offsite_next_falls_back_to_root(self):
        """An off-host 'next' is not honoured (no open redirect)."""
        response = self.client.post(
            self.add_url,
            {
                "name": "Netflix",
                "url": "https://netflix.com",
                "next": "https://evil.example.com/phish",
            },
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(StreamingLink.objects.count(), 1)

    def test_season_variant_scopes_to_season_item(self):
        """The season URL variant attaches the link to the season Item."""
        add_season_url = reverse(
            "add_streaming_link",
            kwargs={
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.SEASON.value,
                "media_id": "67116",
                "season_number": 2,
            },
        )
        self.client.post(
            add_season_url,
            {"name": "Disney", "url": "https://disneyplus.com", "next": "/"},
        )
        item = Item.objects.get(
            media_id="67116", media_type=MediaTypes.SEASON.value, season_number=2
        )
        self.assertEqual(item.streaming_links.get().name, "Disney")


class DeleteStreamingLinkTests(TestCase):
    """POST delete_streaming_link — remove a user link."""

    def setUp(self):
        """Log in and seed one link."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Godfather",
            image="http://example.com/i.jpg",
        )
        self.link = StreamingLink.objects.create(
            item=self.item, name="Netflix", url="https://nf"
        )

    def test_deletes_link(self):
        """A valid POST removes the link and redirects to next."""
        response = self.client.post(
            reverse("delete_streaming_link", kwargs={"link_id": self.link.id}),
            {"next": "/"},
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertFalse(StreamingLink.objects.filter(id=self.link.id).exists())

    def test_missing_link_returns_404(self):
        """Deleting an unknown link id 404s."""
        response = self.client.post(
            reverse("delete_streaming_link", kwargs={"link_id": 999999}),
            {"next": "/"},
        )
        self.assertEqual(response.status_code, 404)
