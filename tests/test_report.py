from datetime import date

from tracker import store, weeks
from tests.base import TrackerTestCase

# O "azi" fixa, ca testele sa nu depinda de ceasul masinii.
TODAY = date(2026, 10, 5)


class ReportTestCase(TrackerTestCase):
    def setUp(self):
        super().setUp()
        self.client = store.create_client({"name": "Restaurant Central"})
        self.accounts = {
            p: store.create_account({"client_id": self.client["id"], "platform": p,
                                     "handle": "@rc"})
            for p in ("instagram", "facebook", "tiktok")}
        # Planul din contract
        for period, ctype, low, high in (("week", "any", 4, 4), ("week", "video", 2, 3),
                                         ("month", "video", 10, 10)):
            store.set_target({"client_id": self.client["id"], "period": period,
                              "content_type": ctype, "target_min": low,
                              "target_max": high})

    def publish(self, day: str, *, title: str, platforms=("instagram",),
                content_type="video", hour=12):
        for platform in platforms:
            store.create_post({
                "account_id": self.accounts[platform]["id"], "content_type": content_type,
                "status": "posted", "posted_at": f"{day} {hour}:00", "title": title,
                "caption": f"text {title}", "url": f"https://x.test/{platform}/{title}",
                "metrics": {"likes": 10}})

    def report(self, month="2026-09"):
        data = store.monthly_report(month, today=TODAY)
        return data["clients"][0] if data["clients"] else None


class WeekAssignmentTests(ReportTestCase):
    def test_weeks_belong_to_the_month_of_their_thursday(self):
        self.assertEqual(weeks.weeks_of_month("2026-09"),
                         ["2026-W36", "2026-W37", "2026-W38", "2026-W39"])
        self.assertEqual(weeks.weeks_of_month("2026-10"),
                         ["2026-W40", "2026-W41", "2026-W42", "2026-W43", "2026-W44"])

    def test_every_week_belongs_to_exactly_one_month(self):
        seen = []
        for month in ("2026-08", "2026-09", "2026-10", "2026-11"):
            seen.extend(weeks.weeks_of_month(month))
        self.assertEqual(len(seen), len(set(seen)))

    def test_month_range_label(self):
        self.assertEqual(weeks.month_range_label("2026-09"), "1 - 30 septembrie 2026")


class MonthlyGoalTests(ReportTestCase):
    def test_monthly_video_goal_counts_only_that_month(self):
        for i, day in enumerate(("2026-09-02", "2026-09-10", "2026-09-30")):
            self.publish(day, title=f"s{i}")
        self.publish("2026-10-01", title="octombrie")   # nu intra in septembrie
        goal = next(g for g in self.report("2026-09")["goals"]
                    if g["content_type"] == "video")
        self.assertEqual(goal["posted"], 3)
        self.assertEqual(goal["target_min"], 10)
        self.assertFalse(goal["done"])

    def test_month_resets_on_the_first(self):
        self.publish("2026-09-30", title="ultima zi", hour=23)
        self.publish("2026-10-01", title="prima zi", hour=1)
        sept = next(g for g in self.report("2026-09")["goals"] if g["content_type"] == "video")
        octo = next(g for g in self.report("2026-10")["goals"] if g["content_type"] == "video")
        self.assertEqual((sept["posted"], octo["posted"]), (1, 1))

    def test_goal_done_at_ten_videos(self):
        for i in range(10):
            self.publish(f"2026-09-{i + 1:02d}", title=f"v{i}")
        goal = next(g for g in self.report("2026-09")["goals"] if g["content_type"] == "video")
        self.assertTrue(goal["done"])
        self.assertEqual(self.report("2026-09")["summary"]["goals_done"], 1)


class WeekStateTests(ReportTestCase):
    def states(self, month="2026-09"):
        return {w["week"]: w["state"] for w in self.report(month)["weeks"]}

    def test_finished_week_meeting_quota_is_done(self):
        # W37 = 7-13 sept: 4 materiale, dintre care 2 video
        self.publish("2026-09-07", title="a", content_type="video")
        self.publish("2026-09-08", title="b", content_type="video")
        self.publish("2026-09-10", title="c", content_type="photo")
        self.publish("2026-09-12", title="d", content_type="photo")
        self.assertEqual(self.states()["2026-W37"], "done")

    def test_finished_week_below_quota_is_missed(self):
        self.publish("2026-09-14", title="doar una")
        self.assertEqual(self.states()["2026-W38"], "missed")

    def test_week_with_today_is_in_progress(self):
        self.assertEqual(self.states("2026-10")["2026-W41"], "in_progress")

    def test_future_week_is_upcoming(self):
        self.assertEqual(self.states("2026-10")["2026-W43"], "upcoming")

    def test_summary_counts_only_finished_weeks(self):
        for day, title in (("2026-09-07", "a"), ("2026-09-08", "b")):
            self.publish(day, title=title, content_type="video")
        for day, title in (("2026-09-10", "c"), ("2026-09-12", "d")):
            self.publish(day, title=title, content_type="photo")
        summary = self.report("2026-09")["summary"]
        self.assertEqual(summary["weeks_finished"], 4)   # toata luna e in trecut
        self.assertEqual(summary["weeks_done"], 1)

    def test_range_target_is_met_at_the_minimum(self):
        self.publish("2026-09-07", title="a", content_type="video")
        self.publish("2026-09-08", title="b", content_type="video")
        week = next(w for w in self.report()["weeks"] if w["week"] == "2026-W37")
        video = next(r for r in week["rows"] if r["content_type"] == "video")
        self.assertTrue(video["is_range"])
        self.assertTrue(video["done"])          # 2 din 2-3


class MaterialsTests(ReportTestCase):
    def test_same_material_on_three_networks_is_one_entry_with_three_links(self):
        self.publish("2026-09-07", title="Burger", platforms=("instagram", "facebook", "tiktok"))
        materials = self.report()["materials"]
        self.assertEqual(len(materials), 1)
        self.assertEqual([p["platform"] for p in materials[0]["platforms"]],
                         ["instagram", "facebook", "tiktok"])
        self.assertTrue(all(p["url"] for p in materials[0]["platforms"]))
        self.assertEqual(materials[0]["interactions"], 30)

    def test_materials_sorted_by_date(self):
        self.publish("2026-09-20", title="tarziu")
        self.publish("2026-09-03", title="devreme")
        self.assertEqual([m["title"] for m in self.report()["materials"]],
                         ["devreme", "tarziu"])

    def test_materials_from_other_months_excluded(self):
        self.publish("2026-08-30", title="august")
        self.publish("2026-09-15", title="septembrie")
        self.assertEqual([m["title"] for m in self.report("2026-09")["materials"]],
                         ["septembrie"])


class ReportScopeTests(ReportTestCase):
    def test_client_without_plan_or_posts_is_omitted(self):
        store.create_client({"name": "Fara nimic"})
        names = [c["name"] for c in store.monthly_report("2026-09", today=TODAY)["clients"]]
        self.assertEqual(names, ["Restaurant Central"])

    def test_client_filter(self):
        other = store.create_client({"name": "Alt client"})
        store.set_target({"client_id": other["id"], "period": "month",
                          "content_type": "video", "target_min": 5})
        only = store.monthly_report("2026-09", client_id=other["id"], today=TODAY)
        self.assertEqual([c["name"] for c in only["clients"]], ["Alt client"])

    def test_in_progress_flag(self):
        self.assertTrue(store.monthly_report("2026-10", today=TODAY)["in_progress"])
        self.assertFalse(store.monthly_report("2026-09", today=TODAY)["in_progress"])

    def test_invalid_month_falls_back_to_current(self):
        self.assertEqual(store.monthly_report("nonsens", today=TODAY)["month"], "2026-10")


if __name__ == "__main__":
    import unittest
    unittest.main()


class MonthSummaryTests(ReportTestCase):
    """"Luna asta: 1 poza, 0 video" - totalul pe tipuri, independent de tinte."""

    def test_one_photo_and_no_video(self):
        self.publish("2026-10-01", title="poza", content_type="photo")
        ms = store.month_summary(self.client["id"], "2026-10")
        self.assertEqual((ms["materials"], ms["photo"], ms["video"]), (1, 1, 0))

    def test_same_material_on_three_networks_counts_once(self):
        self.publish("2026-10-01", title="poza", content_type="photo",
                     platforms=("instagram", "facebook", "tiktok"))
        ms = store.month_summary(self.client["id"], "2026-10")
        self.assertEqual(ms["materials"], 1)
        self.assertEqual(ms["posts"], 3)

    def test_counts_only_the_requested_month(self):
        self.publish("2026-09-30", title="septembrie", content_type="video")
        self.publish("2026-10-01", title="octombrie", content_type="photo")
        self.assertEqual(store.month_summary(self.client["id"], "2026-10")["video"], 0)
        self.assertEqual(store.month_summary(self.client["id"], "2026-09")["video"], 1)

    def test_month_with_nothing_is_all_zero(self):
        ms = store.month_summary(self.client["id"], "2026-10")
        self.assertEqual((ms["materials"], ms["video"], ms["photo"]), (0, 0, 0))

    def test_present_in_report_and_dashboard(self):
        self.publish("2026-10-01", title="poza", content_type="photo")
        report = store.monthly_report("2026-10", today=TODAY)["clients"][0]
        self.assertEqual(report["month_summary"]["photo"], 1)
        dash = store.dashboard(weeks.week_of(TODAY))["clients"][0]
        self.assertEqual(dash["month_summary"]["photo"], 1)
        self.assertEqual(dash["month_summary"]["month"], "2026-10")


class PostsDiagnosticTests(ReportTestCase):
    def test_table_shows_week_month_and_monthly_totals(self):
        import run
        self.publish("2026-10-01", title="Poza noua", content_type="photo")
        self.publish("2026-09-29", title="Video septembrie", content_type="video")
        text = run.format_posts_table(store.list_posts())
        self.assertIn("Poza noua", text)
        self.assertIn("2026-10", text)
        self.assertIn("2026-10: 1  (1 poza)", text)
        self.assertIn("2026-09: 1  (1 video)", text)

    def test_empty_database_explains_what_to_do(self):
        import run
        self.assertIn("--sync", run.format_posts_table([]))
