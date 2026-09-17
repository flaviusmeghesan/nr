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

    def test_recurring_target_applies_to_any_week(self):
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_count": 5})
        self.assertEqual(store.effective_targets(self.account["id"], "2026-W38"),
                         {"video": 5})
        self.assertEqual(store.effective_targets(self.account["id"], "2026-W40"),
                         {"video": 5})

    def test_weekly_override_wins_over_recurring(self):
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_count": 5})
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "week": "2026-W38", "target_count": 8})
        self.assertEqual(store.effective_targets(self.account["id"], "2026-W38")["video"], 8)
        self.assertEqual(store.effective_targets(self.account["id"], "2026-W39")["video"], 5)

    def test_zero_target_removes_it(self):
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_count": 5})
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_count": 0})
        self.assertNotIn("video", store.effective_targets(self.account["id"], "2026-W38"))


class DashboardTests(TrackerTestCase):
    def setUp(self):
        super().setUp()
        self.client = store.create_client({"name": "Client A"})
        self.account = store.create_account(
            {"client_id": self.client["id"], "platform": "instagram", "handle": "@a"})
        store.set_target({"account_id": self.account["id"], "content_type": "video",
                          "target_count": 5})
        store.set_target({"account_id": self.account["id"], "content_type": "photo",
                          "target_count": 3})

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
