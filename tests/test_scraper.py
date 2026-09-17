"""Teste pentru stratul de extractie al scraperului.

Nu ating reteaua: extractia e o functie pura (JSON in -> postari out), exact ca
sa poata fi testata asa. Fixture-urile imita formele reale ale platformelor,
inclusiv variante paralele ale acelorasi campuri.
"""

import unittest

from tests.fixtures import samples
from tracker.sources.scraper import parse_profile_url
from tracker.sources.scraper.parse import as_int, deep, dedupe, timestamp_to_iso, walk
from tracker.sources.scraper.platforms import extract_posts


class ParseHelpersTests(unittest.TestCase):
    def test_walk_finds_deeply_nested_dicts(self):
        tree = {"a": {"b": [{"c": 1}, {"d": 2}]}}
        found = [d for d in walk(tree) if "c" in d or "d" in d]
        self.assertEqual(len(found), 2)

    def test_deep_returns_default_when_path_missing(self):
        self.assertIsNone(deep({"a": {"b": 1}}, "a.x.y"))
        self.assertEqual(deep({"a": {"b": 1}}, "a.b"), 1)

    def test_deep_indexes_into_lists(self):
        self.assertEqual(deep({"a": [{"b": 7}]}, "a.0.b"), 7)

    def test_as_int_handles_abbreviations(self):
        self.assertEqual(as_int(1200), 1200)
        self.assertEqual(as_int("1.2K"), 1200)
        self.assertEqual(as_int("3M"), 3_000_000)
        self.assertEqual(as_int("1,234"), 1234)
        self.assertIsNone(as_int(""))
        self.assertIsNone(as_int("abc"))

    def test_timestamp_handles_seconds_and_milliseconds(self):
        seconds = timestamp_to_iso(1789056000)
        millis = timestamp_to_iso(1789056000_000)
        self.assertEqual(seconds, millis)
        self.assertTrue(seconds.startswith("2026-"))

    def test_timestamp_invalid_returns_empty(self):
        self.assertEqual(timestamp_to_iso(None), "")
        self.assertEqual(timestamp_to_iso("nu e numar"), "")

    def test_dedupe_keeps_richest_copy(self):
        thin = {"external_id": "1", "posted_at": "2026-09-10", "title": "", "metrics": {}}
        rich = {"external_id": "1", "posted_at": "2026-09-10", "title": "x",
                "metrics": {"likes": 5}}
        self.assertEqual(dedupe([thin, rich]), [rich])
        self.assertEqual(dedupe([rich, thin]), [rich])


class InstagramExtractionTests(unittest.TestCase):
    def test_modern_shape(self):
        posts = extract_posts("instagram", [samples.INSTAGRAM_MODERN], "@central")
        self.assertEqual(len(posts), 2)
        reel = posts[0]
        self.assertEqual(reel["content_type"], "video")   # product_type = clips
        self.assertEqual(reel["metrics"], {"likes": 245, "comments": 18, "views": 5300})
        self.assertEqual(reel["title"], "Burger nou in meniu!")
        self.assertIn("/p/C9xAbCdEfGh/", reel["url"])
        self.assertEqual(posts[1]["content_type"], "carousel")  # media_type 8

    def test_legacy_shape_still_works(self):
        """Forma veche foloseste alte denumiri - extractia trebuie sa o prinda la fel."""
        posts = extract_posts("instagram", [samples.INSTAGRAM_LEGACY], "@central")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["content_type"], "photo")
        self.assertEqual(posts[0]["metrics"], {"likes": 88, "comments": 3})

    def test_both_shapes_together_deduplicate_by_id(self):
        posts = extract_posts(
            "instagram", [samples.INSTAGRAM_MODERN, samples.INSTAGRAM_MODERN], "@central")
        self.assertEqual(len(posts), 2)


class TikTokExtractionTests(unittest.TestCase):
    def test_item_list(self):
        posts = extract_posts("tiktok", [samples.TIKTOK_ITEM_LIST], "@restaurantcentral")
        self.assertEqual(len(posts), 2)
        top = posts[0]
        self.assertEqual(top["content_type"], "video")
        self.assertEqual(top["metrics"],
                         {"views": 15200, "likes": 890, "comments": 45, "shares": 23})
        self.assertEqual(top["url"],
                         "https://www.tiktok.com/@restaurantcentral/video/7412345678901234567")

    def test_handle_used_when_author_missing(self):
        payload = {"itemList": [{"id": "999", "desc": "x", "createTime": 1789056000,
                                "stats": {"playCount": 1}}]}
        posts = extract_posts("tiktok", [payload], "@fallbackhandle")
        self.assertIn("@fallbackhandle", posts[0]["url"])


class FacebookExtractionTests(unittest.TestCase):
    def test_page_feed(self):
        posts = extract_posts("facebook", [samples.FACEBOOK_FEED], "@central")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["metrics"], {"likes": 64, "comments": 12, "shares": 5})
        self.assertEqual(posts[0]["content_type"], "photo")


class RobustnessTests(unittest.TestCase):
    def test_noise_yields_nothing_without_crashing(self):
        self.assertEqual(extract_posts("instagram", [samples.NOISE], "@x"), [])
        self.assertEqual(extract_posts("tiktok", [samples.NOISE], "@x"), [])
        self.assertEqual(extract_posts("facebook", [samples.NOISE], "@x"), [])

    def test_unknown_platform_returns_empty(self):
        self.assertEqual(extract_posts("myspace", [samples.TIKTOK_ITEM_LIST], "@x"), [])

    def test_malformed_payloads_do_not_raise(self):
        junk = [None, [], "text", 42, {"a": None}, {"itemList": "nu e lista"}]
        for platform in ("instagram", "tiktok", "facebook"):
            with self.subTest(platform=platform):
                self.assertEqual(extract_posts(platform, junk, "@x"), [])

    def test_post_without_timestamp_is_skipped(self):
        payload = {"itemList": [{"id": "1", "desc": "fara data", "stats": {}}]}
        self.assertEqual(extract_posts("tiktok", [payload], "@x"), [])


class ProfileUrlTests(unittest.TestCase):
    def test_recognises_each_platform(self):
        cases = {
            "https://www.instagram.com/restaurantcentral/": ("instagram", "@restaurantcentral"),
            "instagram.com/restaurant.central": ("instagram", "@restaurant.central"),
            "https://www.tiktok.com/@central?lang=ro": ("tiktok", "@central"),
            "https://www.facebook.com/RestaurantCentral": ("facebook", "@RestaurantCentral"),
            "https://www.facebook.com/profile.php?id=615501234": ("facebook", "@615501234"),
        }
        for url, (platform, handle) in cases.items():
            with self.subTest(url=url):
                parsed = parse_profile_url(url)
                self.assertIsNotNone(parsed, f"nerecunoscut: {url}")
                self.assertEqual(parsed["platform"], platform)
                self.assertEqual(parsed["handle"], handle)

    def test_rejects_non_profile_urls(self):
        for url in ["https://www.instagram.com/p/C9xAbCdEfGh/", "https://example.com/x",
                    "", None, "https://www.instagram.com/reel/abc/"]:
            with self.subTest(url=url):
                self.assertIsNone(parse_profile_url(url))


if __name__ == "__main__":
    unittest.main()
