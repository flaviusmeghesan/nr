# Tracker continut social

Aplicatie locala, pentru agentie, care tine evidenta a ce trebuia postat vs.
ce s-a postat efectiv pe Instagram / Facebook / TikTok pentru fiecare client -
gen „saptamana asta aveam de postat 5 video, sunt 3 postate".

Ruleaza doar pe calculatorul tau (nimic nu pleaca pe internet in afara de
importul optional din platforme), scrisa in Python standard - fara
instalare de pachete.

## Pornire

Ai nevoie doar de Python 3.10+ (verifica cu `python3 --version`).

```bash
python3 run.py
```

Se deschide `http://127.0.0.1:8765` in browser. Baza de date (SQLite) se
creeaza automat in `data/tracker.db`, iar fisierele urcate (poze/video) in
`media/`.

Ca sa vezi cum arata cu date de exemplu, inainte sa introduci pe ale tale:

```bash
python3 run.py --demo
```

Alte optiuni: `--port 9000` (alt port), `--no-browser` (nu deschide singur
browserul).

## Fluxul saptamanal

1. **Setari** - adaugi clientul, contul lui pe fiecare platforma (IG/FB/TikTok)
  si planul: cate video/poze/story-uri trebuie postate. Poti pune un plan
  „implicit" (valabil in fiecare saptamana) si, daca vrei, un numar diferit
  doar pentru saptamana curenta.
2. In timpul saptamanii, colegii adauga postari din tab-ul **Postari** (buton
  „+ Postare noua") - fie ca „planificat" (inainte sa fie live), fie direct
  ca „postat", cu link si eventual fisierul atasat.
3. **Dashboard**-ul arata, per client si cont, cate din tinta au fost deja
  postate ("3/5"), cate mai sunt in lucru si cate au ramas.
4. La final de saptamana (sau oricand), imponti exportul de postari reale al
  clientului din platforma (vezi mai jos) - aplicatia leaga automat postarile
  reale de intrarile deja planificate, in loc sa creeze duplicate.

## De ce import din export, nu conectare directa la conturi

Ideea initiala a fost sa citim automat postarile prin API-urile platformelor
(Meta Graph API, TikTok). Nu merge ca solutie de baza pentru o agentie:

- Meta cere **Advanced Access** (App Review + Business Verification, poate
  dura saptamani) ca sa citesti conturi pe care nu le detii tu direct -
  adica exact conturile clientilor. Fara el, merg doar conturile unde esti
  tu admin/tester in Meta Business Suite.
- TikTok Display API cere aprobarea aplicatiei, similar.

In schimb, agentia **administreaza deja** conturile clientilor in Meta
Business Suite si TikTok Studio/Business Center - iar ambele iti dau un
export CSV cu postarile, fara nicio aprobare:

- **Meta Business Suite** → Content → *Export Data* → CSV (merge si pentru
  Instagram, si pentru Facebook).
- **TikTok Studio** (sau TikTok Business Center) → *Download data* → CSV/XLSX.

Asta functioneaza din prima zi, pentru orice client - prezent sau viitor -
fara sa configurezi nimic per client.

### Cum imponti un export

Din **Setari → Import din export**:

1. Alegi clientul si contul (asta stabileste platforma).
2. Urci fisierul CSV exportat.
3. Aplicatia iti arata coloanele gasite si o **mapare ghicita automat**
  (recunoaste denumiri uzuale ca "Post ID", "Publish Time", "Video views"
  etc., in engleza sau romana). O confirmi sau o corectezi.
4. Apesi Importa. Postarile care se potrivesc cu ceva deja planificat (acelasi
  cont, tip si saptamana) se leaga automat de acea intrare, in loc sa
  duplice - titlul/autorul puse manual raman neatinse. Restul devin postari
  noi, marcate "postat", cu metricile din export (likes/comentarii/etc.).

Daca data viitoare Meta sau TikTok redenumesc o coloana, pur si simplu
corectezi maparea din interfata - se salveaza automat pentru viitor, per
platforma, fara nicio modificare de cod.

### Sincronizare live (optional, doar daca faci vreodata App Review)

Ecranul **Setari → Sincronizare live** ramane pentru cine vrea sa treaca prin
App Review la Meta pentru Instagram/Facebook (permite tragerea automata a
postarilor, fara export manual). Nu e necesar pentru fluxul de zi cu zi.
Pasii, pe scurt:

1. Creezi o aplicatie Meta (o singura data, pe contul agentiei).
2. Contul Instagram al clientului trebuie sa fie Business/Creator, legat de
  o Pagina de Facebook, unde agentia are rol de admin.
3. Pentru conturi ale clientilor (pe care nu le detii tu), Meta cere
  Advanced Access → App Review + Business Verification.
4. Odata aprobat, pui token-ul si ID-ul contului (IG user id / Page id) in
  Setari → Conturi, iar butonul „Sincronizeaza" din ecranul de import trage
  postarile automat.

TikTok nu are un echivalent practic fara sa treci prin acelasi proces de
aprobare - foloseste importul CSV.

## Import rapid (format propriu)

Pentru situatii cand vrei sa introduci multe postari planificate dintr-un
tabel facut de voi (nu un export de platforma), exista un import CSV separat
in acelasi coloane cu care lucreaza aplicatia: `client, platforma, cont, tip,
status, planificat_pe, postat_la, titlu, link, autor, descriere`. Clientii si
conturile lipsa se creeaza automat.

## Structura proiectului

```
run.py                     punct de pornire (python3 run.py)
tracker/
  db.py                    schema SQLite
  store.py                 logica de business + dashboard + reconciliere import
  weeks.py                 saptamani ISO, parsare date din exporturi
  server.py                server HTTP (stdlib) + rutele API
  sources/
    csvfile.py             import generic, condus de mapare de coloane
    presets.py             ghicirea denumirilor de coloane (Meta/TikTok/RO)
    internal_csv.py        import/export in formatul propriu al aplicatiei
    graph.py                sincronizare optionala prin Meta Graph API
    aggregator.py           stub pentru un agregator platit (Ayrshare etc.)
web/                       interfata (HTML/CSS/JS, fara framework)
tests/                     teste (python3 -m unittest discover tests)
```

## Teste

```bash
python3 -m unittest discover tests -v
```

## Extindere viitoare

- Daca numarul de clienti/conturi creste mult, un agregator platit
  (Ayrshare, Phyllo) poate inlocui importul manual cu o singura integrare -
  vezi `tracker/sources/aggregator.py` pentru unde s-ar conecta.
- Adaptorul Graph API (`tracker/sources/graph.py`) e gata de folosit daca
  faci vreodata App Review la Meta.
