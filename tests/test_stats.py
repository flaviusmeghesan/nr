from datetime import date, timedelta

from tracker import store, weeks
from tests.base import TrackerTestCase


class StatsTestCase(TrackerTestCase):
    def setUp(self):
        super().setUp()
        self.client = store.create_client({"name": "Client A"})
        self.ig = store.create_account(
            {"client_id": self.client["id"], "platform": "instagram", "handle": "@a"})
        self.tt = store.create_account(
            {"client_id": self.client["id"], "platform": "tiktok", "handle": "@a"})
        self.week = weeks.current_week()
        self.monday, _ = weeks.week_bounds(self.week)

    def post(self, account, *, metrics=None, title="x", caption="y", day=0,
             content_type="video", status="posted", week_offset=0):
        monday = self.monday + timedelta(weeks=week_offset)
        when = f"{(monday + timedelta(days=day)).isoformat()} 12:00"
        return store.create_post({
            "account_id": account["id"], "content_type": content_type, "status": status,
            "posted_at": when, "title": title, "caption": caption,
            "metrics": metrics or {}})


class SummaryTests(StatsTestCase):
    def test_sums_metrics_and_interactions(self):
        self.post(self.ig, metrics={"likes": 100, "comments": 10, "views": 2000})
        self.post(self.tt, metrics={"likes": 300, "comments": 20, "shares": 5,
                                    "views": 9000}, title="alt", caption="altceva")
        s = store.stats(self.week, "week")["summary"]
        self.assertEqual(s["posts"], 2)
        self.assertEqual((s["likes"], s["comments"], s["shares"], s["views"]),
                         (400, 30, 5, 11000))
        self.assertEqual(s["interactions"], 435)   # fara vizualizari
        self.assertEqual(s["avg_interactions"], 217.5)

    def test_missing_metric_is_none_not_zero(self):
        """Nicio postare nu are 'shares' -> None (interfata arata '-'), nu 0."""
        self.post(self.ig, metrics={"likes": 10, "comments": 1})
        s = store.stats(self.week, "week")["summary"]
        self.assertIsNone(s["shares"])
        self.assertIsNone(s["views"])
        self.assertEqual(s["likes"], 10)

    def test_same_material_on_two_networks_is_one_material(self):
        self.post(self.ig, metrics={"likes": 1}, title="Burger", caption="vino azi")
        self.post(self.tt, metrics={"likes": 1}, title="Burger", caption="vino azi")
        s = store.stats(self.week, "week")["summary"]
        self.assertEqual(s["posts"], 2)
        self.assertEqual(s["materials"], 1)

    def test_only_published_posts_count(self):
        self.post(self.ig, metrics={"likes": 50})
        self.post(self.ig, status="planned", metrics={"likes": 999}, title="p", caption="q")
        self.assertEqual(store.stats(self.week, "week")["summary"]["likes"], 50)

    def test_inactive_client_excluded(self):
        self.post(self.ig, metrics={"likes": 50})
        store.update_client(self.client["id"], {"active": False})
        self.assertEqual(store.stats(self.week, "week")["summary"]["posts"], 0)

    def test_client_filter(self):
        other = store.create_client({"name": "Alt client"})
        other_acc = store.create_account(
            {"client_id": other["id"], "platform": "instagram", "handle": "@b"})
        self.post(self.ig, metrics={"likes": 10})
        self.post(other_acc, metrics={"likes": 500}, title="z", caption="zz")
        mine = store.stats(self.week, "week", client_id=self.client["id"])["summary"]
        self.assertEqual(mine["likes"], 10)

    def test_empty_period_has_zero_posts_and_no_crash(self):
        s = store.stats(self.week, "week")
        self.assertEqual(s["summary"]["posts"], 0)
        self.assertEqual(s["by_platform"], [])
        self.assertEqual(s["top_posts"], [])
        self.assertEqual(len(s["trend"]), store.TREND_WEEKS)


class RangeTests(StatsTestCase):
    def test_week_range_excludes_other_weeks(self):
        self.post(self.ig, metrics={"likes": 10})
        self.post(self.ig, metrics={"likes": 99}, week_offset=-1, title="a", caption="b")
        self.assertEqual(store.stats(self.week, "week")["summary"]["likes"], 10)

    def test_all_range_includes_everything(self):
        self.post(self.ig, metrics={"likes": 10})
        self.post(self.ig, metrics={"likes": 99}, week_offset=-6, title="a", caption="b")
        self.assertEqual(store.stats(self.week, "all")["summary"]["likes"], 109)

    def test_invalid_range_falls_back_to_month(self):
        self.assertEqual(store.stats(self.week, "nonsense")["range"], "month")


class ComparisonTests(StatsTestCase):
    def test_unfinished_period_is_not_compared(self):
        """Saptamana curenta nu s-a terminat: nu o comparam cu cea trecuta, completa."""
        self.post(self.ig, metrics={"likes": 10})
        self.post(self.ig, metrics={"likes": 1000}, week_offset=-1, title="a", caption="b")
        s = store.stats(self.week, "week")["summary"]
        self.assertTrue(s["in_progress"])
        self.assertIsNone(s["posts_change"])
        self.assertIsNone(s["interactions_change"])

    def test_finished_period_is_compared(self):
        past = weeks.shift_week(self.week, -2)
        self.post(self.ig, metrics={"likes": 150}, week_offset=-2)
        self.post(self.ig, metrics={"likes": 100}, week_offset=-3, title="a", caption="b")
        s = store.stats(past, "week")["summary"]
        self.assertFalse(s["in_progress"])
        self.assertEqual(s["interactions_change"], 50.0)   # 100 -> 150

    def test_no_change_when_previous_period_empty(self):
        past = weeks.shift_week(self.week, -2)
        self.post(self.ig, metrics={"likes": 150}, week_offset=-2)
        self.assertIsNone(store.stats(past, "week")["summary"]["interactions_change"])


class BreakdownTests(StatsTestCase):
    def test_by_platform_follows_fixed_order_and_skips_empty(self):
        self.post(self.tt, metrics={"likes": 5})
        self.post(self.ig, metrics={"likes": 7}, title="a", caption="b")
        platforms = [p["platform"] for p in store.stats(self.week, "week")["by_platform"]]
        self.assertEqual(platforms, ["instagram", "tiktok"])   # facebook nu are postari

    def test_by_type_averages_per_post(self):
        self.post(self.ig, metrics={"likes": 100}, content_type="video")
        self.post(self.ig, metrics={"likes": 20}, content_type="photo", title="a", caption="b")
        by_type = {t["content_type"]: t for t in store.stats(self.week, "week")["by_type"]}
        self.assertEqual(by_type["video"]["avg_interactions"], 100)
        self.assertEqual(by_type["photo"]["avg_interactions"], 20)

    def test_top_posts_ranked_by_interactions_and_capped(self):
        for i in range(8):
            self.post(self.ig, metrics={"likes": i * 10}, title=f"p{i}",
                      caption=f"text diferit {i}", day=i % 5)
        top = store.stats(self.week, "week")["top_posts"]
        self.assertEqual(len(top), store.TOP_POSTS)
        scores = [p["interactions"] for p in top]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(top[0]["title"], "p7")

    def test_trend_ends_on_selected_week_and_counts_each_week(self):
        self.post(self.ig, metrics={"likes": 10})
        self.post(self.ig, metrics={"likes": 40}, week_offset=-2, title="a", caption="b")
        trend = store.stats(self.week, "week")["trend"]
        self.assertEqual(trend[-1]["week"], self.week)
        self.assertTrue(trend[-1]["is_selected"])
        self.assertEqual(trend[-1]["interactions"], 10)
        self.assertEqual(trend[-3]["interactions"], 40)


class MonthHelpersTests(StatsTestCase):
    def test_shift_month_across_years(self):
        self.assertEqual(weeks.shift_month("2026-01", -1), "2025-12")
        self.assertEqual(weeks.shift_month("2026-12", 1), "2027-01")
        self.assertEqual(weeks.shift_month("2026-10", -13), "2025-09")

    def test_month_bounds_handles_leap_year(self):
        self.assertEqual(weeks.month_bounds("2024-02")[1], date(2024, 2, 29))
        self.assertEqual(weeks.month_bounds("2026-02")[1], date(2026, 2, 28))


if __name__ == "__main__":
    import unittest
    unittest.main()
