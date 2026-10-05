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


def apply_contract_plan(client_id: int) -> None:
    """Planul unui pachet lunar tipic: 4 postari/saptamana (acelasi material pe toate
    retelele se numara o data), 2-3 dintre ele video, si 10 videoclipuri/luna."""
    for period, content_type, low, high in (("week", "any", 4, 4),
                                            ("week", "video", 2, 3),
                                            ("month", "video", 10, 10)):
        store.set_target({"client_id": client_id, "period": period,
                          "content_type": content_type, "target_min": low,
                          "target_max": high})


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
    apply_contract_plan(client["id"])

    # Postari publicate pe ultimele 8 saptamani (inclusiv asta), cu metrici, ca
    # ecranul de statistici sa aiba ce arata. Numerele sunt inventate, dar
    # deterministe - rularea --demo da mereu acelasi rezultat.
    week = weeks.current_week()
    topics = [("Burger nou in meniu", "Vino sa incerci noul burger!"),
              ("Tur prin bucatarie", "Asa arata bucataria dimineata."),
              ("Desertul zilei", "Papanasi ca la bunica."),
              ("Meniul de pranz", "Mancare de casa, in fiecare zi."),
              ("Echipa noastra", "Ii cunoasteti pe baietii din bucatarie?"),
              ("Cocktailul lunii", "Ceva racoritor pentru seara.")]
    members = ("Ana", "Bogdan", "Flavius")
    for back in range(7, -1, -1):
        monday, _ = weeks.week_bounds(weeks.shift_week(week, -back))
        count = 2 if back == 0 else (4 if back in (2, 3, 6) else 3)   # unele saptamani ating cota de 4, altele nu
        for index in range(count):
            title, caption = topics[(back * 2 + index) % len(topics)]
            when = f"{(monday + timedelta(days=index * 2)).isoformat()} {11 + index * 4}:00"
            strength = 60 + (7 - back) * 18 + (index * 35) + (back * 13) % 40
            content_type = "photo" if index == 2 else "video"
            targets_platforms = accounts if content_type == "video" else ("instagram", "facebook")
            for platform in targets_platforms:
                factor = {"instagram": 1.0, "facebook": 0.55, "tiktok": 1.9}[platform]
                metrics = {"likes": int(strength * factor),
                           "comments": int(strength * factor * 0.09)}
                if platform != "instagram":
                    metrics["shares"] = int(strength * factor * 0.05)
                if content_type == "video" and platform == "tiktok":
                    metrics["views"] = int(strength * factor * 38)
                elif content_type == "video" and platform == "instagram":
                    metrics["views"] = int(strength * 21)
                store.create_post({
                    "account_id": accounts[platform]["id"], "content_type": content_type,
                    "status": "posted", "posted_at": when, "title": title,
                    "caption": caption, "author": members[index % 3],
                    "metrics": metrics})

    print(f"Am creat exemplul 'Restaurant Central' cu planul pe saptamana {week}.")


def do_setup(values: list[str], with_plan: bool) -> int:
    """Creeaza un client si conturile lui din linkuri, intr-o singura comanda."""
    name, links = values[0], values[1:]
    if not links:
        print("  Lipsesc linkurile. Exemplu:\n"
              '    python3 run.py --setup "Restaurant Central" '
              "https://www.instagram.com/pagina/ https://www.tiktok.com/@pagina",
              file=sys.stderr)
        return 1
    client_id = None
    failed = 0
    for link in links:
        try:
            result = server.api_add_from_link({"url": link, "client_name": name})
        except server.ApiError as exc:
            failed += 1
            print(f"  ✗ {link}\n      {exc.message}")
            continue
        client_id = result["client"]["id"]
        account = result["account"]
        state = "adaugat" if result["created"] else "exista deja"
        print(f"  ✓ {account['platform_label']:10} {account['handle']}  ({state})")
    if client_id and with_plan:
        apply_contract_plan(client_id)
        print("  ✓ plan aplicat: 4 postari/sapt., 2-3 video/sapt., 10 video/luna")
    if client_id:
        print(f"\n  Client: {name}. Urmatorul pas: python3 run.py --login, apoi --sync.")
    return 1 if failed == len(links) else 0


def do_login() -> int:
    """Pasul unic de logare: deschide un browser vizibil, tu te loghezi, gata."""
    try:
        sources.scraper.open_login_window()
    except RuntimeError as exc:
        print(f"\n  {exc}\n", file=sys.stderr)
        return 1
    return 0


def do_sync(scrolls: int | None = None) -> int:
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
        result = sources.run(account, limit=300 if scrolls else 50, scrolls=scrolls)
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
    parser.add_argument("--setup", nargs="+", metavar=("CLIENT", "LINK"),
                        help="creeaza un client din linkuri: --setup \"Nume\" link1 link2 ...")
    parser.add_argument("--contract-plan", action="store_true",
                        help="cu --setup: aplica planul (4/sapt., 2-3 video/sapt., 10 video/luna)")
    parser.add_argument("--scrolls", type=int, metavar="N",
                        help="cu --sync: de cate ori derulam pagina (implicit 4). Mai mult = "
                             "postari mai vechi; pentru istoric foloseste ex. --scrolls 25")
    parser.add_argument("--sync", action="store_true",
                        help="sincronizeaza toate conturile acum, fara sa porneasca serverul")
    args = parser.parse_args(argv)

    db.init_db()
    if args.demo:
        seed_demo()
    if args.setup:
        return do_setup(args.setup, args.contract_plan)
    if args.login:
        return do_login()
    if args.sync:
        return do_sync(args.scrolls)

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
