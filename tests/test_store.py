from tracker import store, weeks
from tests.base import TrackerTestCase


class ClientsAccountsTests(TrackerTestCase):
    def test_create_and_list_client(self):
        store.create_client({"name": "Client A"})
        names = [c["name"] for c in store.list_clients()]
        self.assertIn("Client A", names)

    def test_duplicate_client_name_rejected(self):
        store.create_client({"name": "Client A"})
        with self.assertRaises(store.ValidationError):
            store.create_client({"name": "client a"})  # insensibil la majuscule

    def test_create_account_requires_valid_client(self):
        with self.assertRaises(store.ValidationError):
            store.create_account({"client_id": 999, "platform": "instagram", "handle": "@x"})

    def test_create_account_rejects_bad_platform(self):
        client = store.create_client({"name": "Client A"})
        with self.assertRaises(store.ValidationError):
            store.create_account({"client_id": client["id"], "platform": "snapchat", "handle": "@x"})

    def test_deleting_client_cascades_to_accounts(self):
        client = store.create_client({"name": "Client A"})
        account = store.create_account(
            {"client_id": client["id"], "platform": "tiktok", "handle": "@x"})
        store.delete_client(client["id"])
        self.assertIsNone(store.get_account(account["id"]))


class TargetsTests(TrackerTestCase):
    def setUp(self):
        super().setUp()
        client = store.create_client({"name": "Client A"})
        self.account = store.create_account(
            {"client_id": client["id"], "platform": "instagram", "handle": "@a"})

    def _targets(self, week="2026-W38"):
        return store.effective_targets("week", week, account_id=self.account["id"])

    def test_recurring_target_applies_to_any_week(self):
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_min": 5})
        self.assertEqual(self._targets("2026-W38")["video"], {"min": 5, "max": 5})
        self.assertEqual(self._targets("2026-W40")["video"], {"min": 5, "max": 5})

    def test_weekly_override_wins_over_recurring(self):
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_min": 5})
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "period_key": "2026-W38", "target_min": 8})
        self.assertEqual(self._targets("2026-W38")["video"]["min"], 8)
        self.assertEqual(self._targets("2026-W39")["video"]["min"], 5)

    def test_zero_target_removes_it(self):
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_min": 5})
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_min": 0})
        self.assertNotIn("video", self._targets())

    def test_range_target_keeps_min_and_max(self):
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_min": 2, "target_max": 3})
        self.assertEqual(self._targets()["video"], {"min": 2, "max": 3})

    def test_reversed_range_is_normalised(self):
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_min": 5, "target_max": 2})
        self.assertEqual(self._targets()["video"], {"min": 2, "max": 5})

    def test_monthly_target_is_separate_from_weekly(self):
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "period": "week", "target_min": 3})
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "period": "month", "target_min": 10})
        self.assertEqual(self._targets()["video"]["min"], 3)
        monthly = store.effective_targets("month", "2026-09",
                                          account_id=self.account["id"])
        self.assertEqual(monthly["video"]["min"], 10)

    def test_target_needs_client_or_account(self):
        with self.assertRaises(store.ValidationError):
            store.set_target({"content_type": "video", "target_min": 3})

    def test_invalid_period_key_rejected(self):
        with self.assertRaises(store.ValidationError):
            store.set_target({"account_id": self.account["id"], "content_type": "video",
                              "period": "month", "period_key": "2026-W38",
                              "target_min": 3})


class DashboardTests(TrackerTestCase):
    def setUp(self):
        super().setUp()
        self.client = store.create_client({"name": "Client A"})
        self.account = store.create_account(
            {"client_id": self.client["id"], "platform": "instagram", "handle": "@a"})
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_min": 5})
        store.set_target({"account_id": self.account["id"], "content_type": "photo",
                          "target_min": 3})

    def test_three_of_five_posted(self):
        week = weeks.current_week()
        monday, _ = weeks.week_bounds(week)
        for i in range(3):
            store.create_post({"account_id": self.account["id"], "content_type": "video",
                               "status": "posted", "posted_at": monday.isoformat()})
        dash = store.dashboard(week)
        row = next(r for r in dash["clients"][0]["accounts"][0]["rows"]
                  if r["content_type"] == "video")
        self.assertEqual(row["posted"], 3)
        self.assertEqual(row["target"], 5)
        self.assertEqual(row["remaining"], 2)

    def test_planned_posts_count_separately_from_posted(self):
        week = weeks.current_week()
        monday, _ = weeks.week_bounds(week)
        store.create_post({"account_id": self.account["id"], "content_type": "video",
                           "status": "posted", "posted_at": monday.isoformat()})
        store.create_post({"account_id": self.account["id"], "content_type": "video",
                           "status": "planned", "planned_for": monday.isoformat()})
        dash = store.dashboard(week)
        row = next(r for r in dash["clients"][0]["accounts"][0]["rows"]
                  if r["content_type"] == "video")
        self.assertEqual(row["posted"], 1)
        self.assertEqual(row["planned"], 1)

    def test_inactive_account_excluded_by_default(self):
        store.update_account(self.account["id"], {"active": False})
        dash = store.dashboard(weeks.current_week())
        self.assertEqual(dash["clients"], [])

    def test_overdue_counts_unposted_from_past_weeks(self):
        past_week = weeks.shift_week(weeks.current_week(), -2)
        monday, _ = weeks.week_bounds(past_week)
        store.create_post({"account_id": self.account["id"], "content_type": "video",
                           "status": "planned", "planned_for": monday.isoformat()})
        dash = store.dashboard(weeks.current_week())
        self.assertEqual(dash["overdue"], 1)


class ImportPostReconciliationTests(TrackerTestCase):
    def setUp(self):
        super().setUp()
        self.client = store.create_client({"name": "Client A"})
        self.account = store.create_account(
            {"client_id": self.client["id"], "platform": "instagram", "handle": "@a"})

    def test_links_to_planned_post_instead_of_duplicating(self):
        week = weeks.current_week()
        monday, _ = weeks.week_bounds(week)
        planned = store.create_post({
            "account_id": self.account["id"], "content_type": "video", "status": "planned",
            "planned_for": monday.isoformat(), "title": "Reel produs nou", "author": "Ana"})

        result = store.import_post(self.account["id"], "media-1", {
            "content_type": "video", "posted_at": f"{monday.isoformat()} 10:00",
            "url": "https://instagram.com/p/x", "metrics": {"likes": 10}})

        self.assertTrue(result["linked_planned"])
        self.assertFalse(result["created"])
        self.assertEqual(result["post"]["id"], planned["id"])
        self.assertEqual(result["post"]["status"], "posted")
        self.assertEqual(result["post"]["title"], "Reel produs nou")  # pastrat, nu suprascris
        self.assertEqual(result["post"]["author"], "Ana")
        self.assertEqual(len(store.list_posts(week=week)), 1)

    def test_creates_new_post_when_nothing_planned(self):
        week = weeks.current_week()
        monday, _ = weeks.week_bounds(week)
        result = store.import_post(self.account["id"], "media-2", {
            "content_type": "photo", "posted_at": monday.isoformat()})
        self.assertTrue(result["created"])
        self.assertFalse(result["linked_planned"])

    def test_reimport_same_external_id_updates_not_duplicates(self):
        week = weeks.current_week()
        monday, _ = weeks.week_bounds(week)
        first = store.import_post(self.account["id"], "media-3", {
            "content_type": "video", "posted_at": monday.isoformat(),
            "metrics": {"likes": 5}})
        second = store.import_post(self.account["id"], "media-3", {
            "content_type": "video", "posted_at": monday.isoformat(),
            "metrics": {"likes": 50}})
        self.assertFalse(second["created"])
        self.assertFalse(second["linked_planned"])
        self.assertEqual(first["post"]["id"], second["post"]["id"])
        self.assertEqual(second["post"]["metrics"]["likes"], 50)
        self.assertEqual(len(store.list_posts(week=week)), 1)

    def test_does_not_link_across_different_content_types(self):
        week = weeks.current_week()
        monday, _ = weeks.week_bounds(week)
        store.create_post({"account_id": self.account["id"], "content_type": "photo",
                           "status": "planned", "planned_for": monday.isoformat()})
        result = store.import_post(self.account["id"], "media-4", {
            "content_type": "video", "posted_at": monday.isoformat()})
        self.assertTrue(result["created"])
        self.assertEqual(len(store.list_posts(week=week)), 2)


if __name__ == "__main__":
    import unittest
    unittest.main()


class ContentGroupingTests(TrackerTestCase):
    """Acelasi material publicat pe mai multe retele trebuie numarat o singura data.

    Semnalul principal e textul postarii; timpul e doar o limita in jurul lui.
    """

    def setUp(self):
        super().setUp()
        self.client = store.create_client({"name": "Client A"})
        self.accounts = {
            platform: store.create_account(
                {"client_id": self.client["id"], "platform": platform, "handle": "@a"})
            for platform in ("instagram", "facebook", "tiktok")}
        self.week = weeks.current_week()
        self.monday, _ = weeks.week_bounds(self.week)

    def _post(self, platform, *, title="", caption="", hour=10, day=0,
              content_type="video", status="posted"):
        when = f"{self.monday.isoformat()} {hour:02d}:00"
        if day:
            from datetime import timedelta
            when = f"{(self.monday + timedelta(days=day)).isoformat()} {hour:02d}:00"
        return store.create_post({
            "account_id": self.accounts[platform]["id"], "content_type": content_type,
            "status": status, "posted_at": when, "title": title, "caption": caption})

    def _groups(self):
        return {p["content_group"] for p in store.list_posts(week=self.week)}

    def test_same_caption_across_platforms_is_one_group(self):
        for platform in ("instagram", "facebook", "tiktok"):
            self._post(platform, title="Burger nou", caption="Vino sa incerci!")
        self.assertEqual(len(self._groups()), 1)

    def test_different_materials_stay_separate(self):
        for platform in ("instagram", "facebook", "tiktok"):
            self._post(platform, title="Burger nou", caption="Vino sa incerci!", hour=10)
            self._post(platform, title="Tur bucatarie", caption="Asa arata dimineata.",
                       hour=15)
        self.assertEqual(len(self._groups()), 2)

    def test_hashtags_and_links_ignored_when_matching(self):
        self._post("instagram", title="Burger nou",
                   caption="Vino azi! #food #cluj @noi https://x.co/1")
        self._post("tiktok", title="Burger nou", caption="Vino azi!")
        self.assertEqual(len(self._groups()), 1)

    def test_same_platform_twice_is_never_grouped(self):
        """Doua postari pe acelasi cont sunt doua bucati, chiar cu acelasi text."""
        self._post("instagram", title="Acelasi text", caption="identic")
        self._post("instagram", title="Acelasi text", caption="identic")
        self.assertEqual(len(self._groups()), 2)

    def test_different_content_types_not_grouped(self):
        self._post("instagram", title="Burger", caption="Vino azi", content_type="video")
        self._post("facebook", title="Burger", caption="Vino azi", content_type="photo")
        self.assertEqual(len(self._groups()), 2)

    def test_same_text_too_far_apart_not_grouped(self):
        self._post("instagram", title="Burger", caption="Vino azi", day=0)
        self._post("facebook", title="Burger", caption="Vino azi", day=5)
        self.assertEqual(len(self._groups()), 2)

    def test_without_text_only_a_tight_window_groups(self):
        self._post("instagram", hour=10)
        self._post("facebook", hour=11)   # in fereastra stransa -> acelasi material
        self.assertEqual(len(self._groups()), 1)

    def test_without_text_distant_posts_stay_separate(self):
        self._post("instagram", hour=8)
        self._post("facebook", hour=20)   # peste fereastra oarba -> materiale diferite
        self.assertEqual(len(self._groups()), 2)

    def test_client_target_counts_groups_not_posts(self):
        store.set_target({"client_id": self.client["id"], "period": "week",
                          "content_type": "any", "target_min": 4})
        for platform in ("instagram", "facebook", "tiktok"):
            self._post(platform, title="Material 1", caption="text unu", hour=10)
            self._post(platform, title="Material 2", caption="text doi", hour=16)

        dash = store.dashboard(self.week)
        row = dash["clients"][0]["rows"][0]
        self.assertEqual(len(store.list_posts(week=self.week)), 6)  # 6 postari reale
        self.assertEqual(row["posted"], 2)                          # dar 2 materiale
        self.assertEqual(row["remaining"], 2)

    def test_account_target_still_counts_every_post(self):
        """Pe tinta unui cont anume numaram postarile lui, nu grupurile."""
        store.set_target({"account_id": self.accounts["instagram"]["id"],
                          "period": "week", "content_type": "video", "target_min": 3})
        self._post("instagram", title="Unu", caption="a", hour=9)
        self._post("instagram", title="Doi", caption="b", hour=12)
        dash = store.dashboard(self.week)
        account_row = next(a for a in dash["clients"][0]["accounts"]
                           if a["platform"] == "instagram")["rows"][0]
        self.assertEqual(account_row["posted"], 2)

    def test_range_target_is_done_at_minimum(self):
        store.set_target({"client_id": self.client["id"], "period": "week",
                          "content_type": "video", "target_min": 2, "target_max": 3})
        for hour, name in ((10, "unu"), (16, "doi")):
            for platform in ("instagram", "tiktok"):
                self._post(platform, title=name, caption=f"text {name}", hour=hour)
        row = store.dashboard(self.week)["clients"][0]["rows"][0]
        self.assertTrue(row["is_range"])
        self.assertEqual(row["posted"], 2)
        self.assertTrue(row["done"])

    def test_monthly_target_counts_across_weeks(self):
        store.set_target({"client_id": self.client["id"], "period": "month",
                          "content_type": "video", "target_min": 10})
        self._post("instagram", title="unu", caption="a", day=0)
        self._post("instagram", title="doi", caption="b", day=1)
        row = store.dashboard(self.week)["clients"][0]["rows"][0]
        self.assertEqual(row["period"], "month")
        self.assertEqual(row["posted"], 2)
        self.assertEqual(row["remaining"], 8)
