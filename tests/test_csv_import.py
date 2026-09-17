from tracker import store, weeks
from tracker.sources import csvfile, internal_csv, presets
from tests.base import TrackerTestCase


class PresetsTests(TrackerTestCase):
    def test_guess_mapping_meta_style_headers(self):
        headers = ["Post ID", "Publish Time", "Post Type", "Description",
                  "Permalink", "Likes", "Comments"]
        mapping = presets.guess_mapping(headers)
        self.assertEqual(mapping["external_id"], "Post ID")
        self.assertEqual(mapping["posted_at"], "Publish Time")
        self.assertEqual(mapping["content_type"], "Post Type")
        self.assertEqual(mapping["metric_likes"], "Likes")
        self.assertEqual(mapping["metric_comments"], "Comments")

    def test_guess_mapping_tiktok_style_headers(self):
        headers = ["Video ID", "Create Time", "Video Description", "Share Url",
                  "Total Views", "Total Likes"]
        mapping = presets.guess_mapping(headers)
        self.assertEqual(mapping["external_id"], "Video ID")
        self.assertEqual(mapping["posted_at"], "Create Time")
        self.assertEqual(mapping["metric_views"], "Total Views")

    def test_guess_mapping_missing_field_is_none(self):
        mapping = presets.guess_mapping(["Random Column"])
        self.assertIsNone(mapping["posted_at"])

    def test_normalize_header(self):
        self.assertEqual(presets.normalize_header("  Publish_Time  "), "publish time")
        self.assertEqual(presets.normalize_header("Post-Type:"), "post type")

    def test_guess_content_type_aliases(self):
        self.assertEqual(presets.guess_content_type("Reel"), "video")
        self.assertEqual(presets.guess_content_type("Carousel Album"), "carousel")
        self.assertEqual(presets.guess_content_type(""), "video")
        self.assertEqual(presets.guess_content_type("", default="photo"), "photo")


class CsvFilePreviewTests(TrackerTestCase):
    def setUp(self):
        super().setUp()
        client = store.create_client({"name": "Client A"})
        self.account = store.create_account(
            {"client_id": client["id"], "platform": "instagram", "handle": "@a"})

    def test_preview_empty_csv(self):
        result = csvfile.preview("", platform="instagram")
        self.assertIn("error", result)

    def test_preview_reuses_saved_profile(self):
        store.save_import_profile("instagram", {"posted_at": "Custom Date Col"})
        result = csvfile.preview("Custom Date Col,Other\n2026-09-15,x\n", platform="instagram")
        self.assertEqual(result["mapping"]["posted_at"], "Custom Date Col")
        self.assertEqual(result["profile_name"], "implicit")

    def test_preview_drops_stale_mapping_column(self):
        store.save_import_profile("instagram", {"posted_at": "Column That Is Gone"})
        result = csvfile.preview("Publish Time,Other\n2026-09-15,x\n", platform="instagram")
        # coloana salvata nu mai exista in fisierul curent -> ghicim din nou
        self.assertEqual(result["mapping"]["posted_at"], "Publish Time")


class CsvFileImportTests(TrackerTestCase):
    def setUp(self):
        super().setUp()
        self.client = store.create_client({"name": "Client A"})
        self.account = store.create_account(
            {"client_id": self.client["id"], "platform": "instagram", "handle": "@a"})
        self.week = weeks.current_week()
        self.monday, _ = weeks.week_bounds(self.week)
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_min": 5})

    def _csv(self):
        return (
            "Post ID,Publish Time,Post Type,Description,Permalink,Likes,Comments,Video views\n"
            f"media_111,{self.monday.isoformat()} 10:00,Video,Produs nou,"
            "https://instagram.com/p/aaa,120,15,900\n"
            f"media_112,{self.monday.isoformat()} 14:30,Video,Testimonial,"
            "https://instagram.com/p/bbb,80,5,400\n"
            f"media_113,{self.monday.isoformat()} 18:00,Photo,Din atelier,"
            "https://instagram.com/p/ccc,50,2,\n"
        )

    def test_import_links_planned_and_creates_rest(self):
        store.create_post({"account_id": self.account["id"], "content_type": "video",
                           "status": "planned", "planned_for": self.monday.isoformat(),
                           "title": "Reel produs nou", "author": "Ana"})
        store.create_post({"account_id": self.account["id"], "content_type": "video",
                           "status": "planned", "planned_for": self.monday.isoformat(),
                           "title": "Reel testimonial", "author": "Bogdan"})

        mapping = presets.guess_mapping(
            ["Post ID", "Publish Time", "Post Type", "Description", "Permalink",
            "Likes", "Comments", "Video views"])
        report = csvfile.import_rows(self._csv(), self.account, mapping)

        self.assertEqual(report["created"], 1)      # doar poza
        self.assertEqual(report["linked_planned"], 2)  # cele 2 video-uri planificate
        self.assertEqual(report["errors"], [])

        posts = store.list_posts(week=self.week)
        self.assertEqual(len(posts), 3)
        authors = {p["title"]: p["author"] for p in posts}
        self.assertEqual(authors["Reel produs nou"], "Ana")
        self.assertEqual(authors["Reel testimonial"], "Bogdan")

    def test_reimport_same_file_does_not_duplicate(self):
        mapping = presets.guess_mapping(
            ["Post ID", "Publish Time", "Post Type", "Description", "Permalink",
            "Likes", "Comments", "Video views"])
        csvfile.import_rows(self._csv(), self.account, mapping)
        second = csvfile.import_rows(self._csv(), self.account, mapping)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 3)
        self.assertEqual(len(store.list_posts(week=self.week)), 3)

    def test_import_saves_and_reuses_profile(self):
        mapping = presets.guess_mapping(
            ["Post ID", "Publish Time", "Post Type", "Description", "Permalink",
            "Likes", "Comments", "Video views"])
        csvfile.import_rows(self._csv(), self.account, mapping, save_profile=True)
        saved = store.get_import_profile("instagram")
        self.assertEqual(saved["mapping"]["posted_at"], "Publish Time")

    def test_missing_required_field_reports_error_without_crashing(self):
        report = csvfile.import_rows(
            "A,B\n1,2\n", self.account, {"posted_at": None})
        self.assertEqual(report["created"], 0)
        self.assertTrue(report["errors"])

    def test_row_with_unparseable_date_is_skipped_not_fatal(self):
        csv_text = ("Post ID,Publish Time\nmedia_1,not-a-date\n"
                    f"media_2,{self.monday.isoformat()}\n")
        mapping = {"external_id": "Post ID", "posted_at": "Publish Time"}
        report = csvfile.import_rows(csv_text, self.account, mapping)
        self.assertEqual(report["created"], 1)
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(len(report["errors"]), 1)

    def test_fallback_external_id_when_column_missing(self):
        csv_text = f"Publish Time,Description\n{self.monday.isoformat()},Fara ID in export\n"
        mapping = {"posted_at": "Publish Time", "caption": "Description"}
        report = csvfile.import_rows(csv_text, self.account, mapping)
        self.assertEqual(report["created"], 1)
        post = store.list_posts(week=self.week)[0]
        self.assertTrue(post["external_id"].startswith("gen-"))


class InternalCsvRoundTripTests(TrackerTestCase):
    def test_export_then_reimport_preserves_counts(self):
        client = store.create_client({"name": "Client A"})
        account = store.create_account(
            {"client_id": client["id"], "platform": "facebook", "handle": "@a"})
        week = weeks.current_week()
        monday, _ = weeks.week_bounds(week)
        store.create_post({"account_id": account["id"], "content_type": "video",
                           "status": "posted", "posted_at": monday.isoformat(),
                           "title": "Clip 1", "author": "Ana"})

        csv_text = internal_csv.export_csv(week=week)
        self.assertIn("Clip 1", csv_text)

        # golim si reimportam - clientul/contul se recreeaza automat din CSV
        store.delete_client(client["id"])
        self.assertEqual(store.list_posts(week=week), [])

        report = internal_csv.import_csv(csv_text)
        self.assertEqual(report["imported"], 1)
        self.assertEqual(len(store.list_posts(week=week)), 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
