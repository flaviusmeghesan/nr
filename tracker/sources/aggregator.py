"""Stub pentru un agregator platit (Ayrshare, Phyllo, etc.).

Nu e apelat de nicaieri momentan. Daca numarul de clienti/conturi ajunge sa
justifice un abonament, un agregator ca Ayrshare rezolva dintr-o singura
integrare autentificarea + citirea postarilor pentru IG/FB/TikTok (si altele),
fara App Review separat pentru fiecare platforma - review-ul il face
furnizorul, o singura data.

Cand devine relevant, implementarea urmeaza acelasi contract ca `graph.py`:

    def sync_account(account: dict, limit: int = 50) -> dict:
        ...
        return {"ok": True/False, "created": int, "updated": int, "error": str}

si se adauga in `tracker/sources/__init__.py::run()`.
"""
