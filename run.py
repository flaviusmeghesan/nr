#!/usr/bin/env python3
"""Porneste tracker-ul de continut social media.

    python3 run.py                  # deschide http://127.0.0.1:8765
    python3 run.py --port 9000
    python3 run.py --demo           # adauga un client de exemplu la prima pornire
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from tracker import db, server, store, weeks


def seed_demo() -> None:
    """Date de exemplu, ca sa vezi cum arata dashboard-ul inainte sa introduci ale tale."""
    if store.list_clients():
        print("Baza de date are deja date - sar peste --demo.")
        return
    client = store.create_client({"name": "Client Demo", "notes": "Exemplu, sterge-l cand vrei."})
    for name in ("Ana", "Bogdan", "Flavius"):
        store.create_member({"name": name})
    plan = {"instagram": {"video": 5, "photo": 3, "story": 5},
            "facebook": {"video": 3, "photo": 2},
            "tiktok": {"video": 4}}
    week = weeks.current_week()
    for platform, targets in plan.items():
        account = store.create_account(
            {"client_id": client["id"], "platform": platform, "handle": "@clientdemo"})
        for content_type, count in targets.items():
            store.set_target({"account_id": account["id"], "content_type": content_type,
                              "target_count": count})
        if platform == "instagram":
            monday, _ = weeks.week_bounds(week)
            for i in range(3):
                store.create_post({
                    "account_id": account["id"], "content_type": "video", "status": "posted",
                    "posted_at": monday.isoformat(), "title": f"Reel demo {i + 1}",
                    "author": ("Ana", "Bogdan", "Flavius")[i]})
    print(f"Am creat clientul demo cu plan pentru saptamana {week}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tracker continut social media")
    parser.add_argument("--host", default="127.0.0.1", help="implicit 127.0.0.1 (doar local)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="nu deschide browserul")
    parser.add_argument("--demo", action="store_true", help="adauga date de exemplu")
    args = parser.parse_args(argv)

    db.init_db()
    if args.demo:
        seed_demo()

    try:
        httpd = server.serve(args.host, args.port)
    except OSError as exc:
        print(f"Nu pot porni pe {args.host}:{args.port} - {exc}\n"
              f"Incearca: python3 run.py --port {args.port + 1}", file=sys.stderr)
        return 1

    url = f"http://{args.host}:{args.port}/"
    print(f"\n  Tracker pornit:  {url}")
    print(f"  Baza de date:    {db.db_path()}")
    print(f"  Media:           {db.MEDIA_DIR}")
    print("\n  Opreste cu Ctrl+C.\n")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Inchis.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
