import json
import threading
import urllib.error
import urllib.request

from tracker import server
from tests.base import TrackerTestCase


class ServerTestCase(TrackerTestCase):
    """Porneste un server real pe un port liber, pentru fiecare test."""

    def setUp(self):
        super().setUp()
        self.httpd = server.serve("127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        super().tearDown()

    def call(self, method, path, data=None, raw=False, headers=None):
        body = None
        hdrs = dict(headers or {})
        if data is not None:
            if raw:
                body = data if isinstance(data, bytes) else data.encode("utf-8")
            else:
                body = json.dumps(data).encode("utf-8")
                hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=body, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


class StaticFilesTests(ServerTestCase):
    def test_index_served(self):
        # index.html nu e JSON, deci nu trece prin self.call() (care asteapta JSON)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn(b"<html", resp.read()[:200])

    def test_unknown_static_file_404(self):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/nu-exista.js")
            self.fail("ar trebui sa dea 404")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)


class ApiCrudTests(ServerTestCase):
    def test_bootstrap_has_expected_keys(self):
        status, data = self.call("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        for key in ("clients", "accounts", "members", "platforms", "content_types", "statuses"):
            self.assertIn(key, data)

    def test_create_client_account_target_and_post(self):
        status, client = self.call("POST", "/api/clients", {"name": "Client API"})
        self.assertEqual(status, 200)

        status, account = self.call("POST", "/api/accounts", {
            "client_id": client["id"], "platform": "tiktok", "handle": "@apitest"})
        self.assertEqual(status, 200)

        status, _ = self.call("POST", "/api/targets", {
            "account_id": account["id"], "content_type": "video", "target_count": 4})
        self.assertEqual(status, 200)

        status, post = self.call("POST", "/api/posts", {
            "account_id": account["id"], "content_type": "video", "status": "posted",
            "posted_at": "2026-09-15"})
        self.assertEqual(status, 200)

        status, dash = self.call("GET", "/api/dashboard?week=2026-W38")
        self.assertEqual(status, 200)
        row = dash["clients"][0]["accounts"][0]["rows"][0]
        self.assertEqual(row["posted"], 1)
        self.assertEqual(row["target"], 4)

        status, _ = self.call("DELETE", f"/api/posts/{post['id']}")
        self.assertEqual(status, 200)

    def test_validation_error_returns_400(self):
        status, data = self.call("POST", "/api/clients", {"name": ""})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_route_returns_404(self):
        status, data = self.call("GET", "/api/nu-exista")
        self.assertEqual(status, 404)


class ImportRoutesTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        _, self.client = self.call("POST", "/api/clients", {"name": "Client API"})
        _, self.account = self.call("POST", "/api/accounts", {
            "client_id": self.client["id"], "platform": "tiktok", "handle": "@apitest"})

    def test_preview_then_commit(self):
        csv_text = ("Video ID,Create Time,Video Description,Share Url,Total Views\n"
                   "v1,2026-09-15 10:00,Clip tare,https://tiktok.com/@x/v1,5000\n")
        status, preview = self.call(
            "POST", "/api/import/preview?platform=tiktok", csv_text, raw=True)
        self.assertEqual(status, 200)
        self.assertEqual(preview["mapping"]["posted_at"], "Create Time")

        status, report = self.call("POST", "/api/import/commit", {
            "account_id": self.account["id"], "csv": csv_text,
            "mapping": preview["mapping"], "save_profile": True})
        self.assertEqual(status, 200)
        self.assertEqual(report["created"], 1)

        status, profiles = self.call("GET", "/api/import-profiles")
        self.assertEqual(status, 200)
        self.assertEqual(len(profiles["profiles"]), 1)

    def test_commit_without_account_fails_cleanly(self):
        status, data = self.call("POST", "/api/import/commit", {
            "csv": "A,B\n1,2\n", "mapping": {}})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_export_csv_route(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/export.csv", method="GET")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/csv", resp.headers.get("Content-Type", ""))


if __name__ == "__main__":
    import unittest
    unittest.main()
