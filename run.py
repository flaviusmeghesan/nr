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
from datetime import timedelta

from tracker import db, server, sources, store, weeks


def seed_demo() -> None:
    """Exemplu bazat pe un pachet real de agentie, ca sa vezi imediat cum arata.

    Cotele sunt cele dintr-un abonament lunar tipic: 4 postari pe saptamana
    (acelasi material publicat pe toate retelele, numarat o singura data),
    2-3 dintre ele video, si 10 videoclipuri pe luna.
    """
    if store.list_clients():
        print("Baza de date are deja date - sar peste --demo.")
        return

    client = store.create_client({
        "name": "Restaurant Central",
        "notes": "Exemplu. Sterge-l cand adaugi clientii reali."})
    for name in ("Ana", "Bogdan", "Flavius"):
        store.create_member({"name": name})

    accounts = {}
    for platform, handle in (("instagram", "@restaurantcentral"),
                             ("facebook", "@restaurantcentral"),
                             ("tiktok", "@restaurantcentral")):
        accounts[platform] = store.create_account(
            {"client_id": client["id"], "platform": platform, "handle": handle})

    # Planul din contract - tinte pe client, deci acelasi material publicat pe
    # toate cele trei retele se numara o singura data.
    store.set_target({"client_id": client["id"], "period": "week",
                      "content_type": "any", "target_min": 4})
    store.set_target({"client_id": client["id"], "period": "week",
                      "content_type": "video", "target_min": 2, "target_max": 3})
    store.set_target({"client_id": client["id"], "period": "month",
                      "content_type": "video", "target_min": 10})

    # Doua materiale deja publicate saptamana asta, fiecare pe toate retelele.
    week = weeks.current_week()
    monday, _ = weeks.week_bounds(week)
    materials = [("Burger nou in meniu", "Vino sa incerci noul burger!", 0, 11),
                 ("Tur prin bucatarie", "Asa arata bucataria dimineata.", 1, 16)]
    for index, (title, caption, day, hour) in enumerate(materials):
        when = f"{(monday + timedelta(days=day)).isoformat()} {hour}:00"
        for platform in accounts:
            store.create_post({
                "account_id": accounts[platform]["id"], "content_type": "video",
                "status": "posted", "posted_at": when, "title": title,
                "caption": caption, "author": ("Ana", "Bogdan")[index]})

    print(f"Am creat exemplul 'Restaurant Central' cu planul pe saptamana {week}.")


def do_login() -> int:
    """Pasul unic de logare: deschide un browser vizibil, tu te loghezi, gata."""
    try:
        sources.scraper.open_login_window()
    except RuntimeError as exc:
        print(f"\n  {exc}\n", file=sys.stderr)
        return 1
    return 0


def do_sync() -> int:
    """Sincronizeaza toate conturile active si scrie un rezumat in terminal."""
    accounts = [a for a in store.list_accounts() if a.get("active")]
    if not accounts:
        print("  Niciun cont activ. Adauga unul in aplicatie (Setari > Conturi).")
        return 0

    available, hint = sources.scraper.is_available()
    if not available:
        print(f"\n  {hint}\n", file=sys.stderr)
        return 1

    failures = 0
    for account in accounts:
        label = f"{account['client_name']} · {account['platform_label']} {account['handle']}"
        print(f"  {label} ... ", end="", flush=True)
        result = sources.run(account)
        if result["ok"]:
            print(f"{result['created']} noi, {result['updated']} actualizate, "
                  f"{result['linked_planned']} legate de plan")
        else:
            failures += 1
            print(f"esuat: {result['error']}")
    return 1 if failures == len(accounts) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tracker continut social media")
    parser.add_argument("--host", default="127.0.0.1", help="implicit 127.0.0.1 (doar local)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="nu deschide browserul")
    parser.add_argument("--demo", action="store_true", help="adauga date de exemplu")
    parser.add_argument("--login", action="store_true",
                        help="deschide un browser ca sa te loghezi o data in conturi")
    parser.add_argument("--sync", action="store_true",
                        help="sincronizeaza toate conturile acum, fara sa porneasca serverul")
    args = parser.parse_args(argv)

    db.init_db()
    if args.demo:
        seed_demo()
    if args.login:
        return do_login()
    if args.sync:
        return do_sync()

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
