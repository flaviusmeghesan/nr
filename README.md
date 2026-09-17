# Tracker continut social

Aplicatie locala, pentru agentie, care tine evidenta a ce trebuia postat vs.
ce s-a postat efectiv pe Instagram / Facebook / TikTok pentru fiecare client -
gen „saptamana asta aveam de postat 5 video, sunt 3 postate".

Ruleaza doar pe calculatorul tau. Nucleul e scris in Python standard, fara
pachete de instalat; singura parte care cere ceva in plus e sincronizarea
automata (Playwright), si e optionala.

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
browserul), `--login` (logare unica pentru sincronizare), `--sync`
(sincronizeaza toate conturile si iese).

Pentru sincronizarea automata ai nevoie in plus de Playwright - vezi mai jos.
Fara el, restul aplicatiei merge normal.

## Cum se foloseste

**O data per client:** in Setari, lipesti linkurile paginilor lui si scrii
planul din contract (ex. 4 postari/saptamana, 2-3 video/saptamana, 10 video/luna).

**In fiecare zi/saptamana:** rulezi `python3 run.py --sync`. Postarile reale se
trag singure de pe pagini, indiferent care dintre colegi le-a publicat.

**Cand vrei sa stii cum stai:** deschizi aplicatia. Dashboard-ul arata, pe
client, cat din plan e realizat ("2/4 postari saptamana asta", "2/10 video luna
asta") si cate zile mai sunt.

Optional, cine vrea poate adauga din timp postari ca „planificat" (tab-ul
**Postari** > „+ Postare noua"), iar sincronizarea le leaga automat de postarea
reala cand apare - asa vezi si ce e in lucru, nu doar ce s-a publicat.

## Sincronizare automata (recomandat)

Aplicatia deschide paginile pe care le administrezi intr-un browser real si
citeste postarile de acolo - aceleasi date pe care le vezi si tu cand intri pe
pagina. Nu ai de configurat conturi, token-uri sau aprobari.

**Pasul unic de pornire:**

```bash
pip install playwright
playwright install chromium
python3 run.py --login
```

Ultima comanda deschide o fereastra de browser. Te loghezi in conturile de care
ai nevoie (Instagram / Facebook / TikTok), inchizi fereastra, gata. Sesiunea
ramane salvata in `data/browser-profile/`, exact ca intr-un Chrome obisnuit -
parolele nu trec prin aplicatie si nu sunt salvate de ea.

Daca ai deja Chrome instalat si nu vrei sa mai descarci unul, pune calea in
`TRACKER_BROWSER_PATH` si sari peste `playwright install`.

**Adaugarea unui client nou** dureaza cat dureaza sa lipesti niste linkuri:
Setari > *Adauga conturi din link*, pui linkurile paginilor (cate unul pe linie),
scrii numele clientului, gata. Platforma si numele contului se recunosc singure.

**Sincronizarea:** butonul `Sincronizeaza` din dreptul fiecarui cont, sau dintr-o
data pentru toate:

```bash
python3 run.py --sync
```

Postarile gasite se leaga automat de ce era deja planificat (acelasi cont, tip si
saptamana), in loc sa creeze duplicate.

### Ce ia si ce nu ia

Ia: postarea, data, tipul (video/poza/carusel), linkul, textul, si metricile
publice - aprecieri, comentarii, vizualizari, distribuiri (in functie de retea).

**Nu ia, si nu are cum:** reach, impresii, salvari, vizite pe profil. Alea nu
sunt publice nicaieri, exista doar in analytics-ul proprietarului contului. Daca
un client cere reach in raport, datele alea se scot din Meta Business Suite si se
aduc aici prin importul CSV de mai jos. La fel, story-urile dispar in 24h si nu
pot fi urmarite automat.

### Cand se strica (pentru ca se va strica)

Retelele isi schimba periodic structura paginilor. Ca sa fie usor de reparat,
scraperul nu citeste HTML-ul randat, ci asculta raspunsurile JSON pe care pagina
si le cere singura, si recunoaste postarile dupa forma campurilor, nu dupa pozitia
lor. Cand tot nu gaseste nimic, salveaza in `data/debug/` pagina, un screenshot si
raspunsurile primite - cu folderul ala se poate repara rapid.

Cel mai frecvent motiv pentru "nu am gasit nicio postare" nu e o schimbare de
format, ci sesiunea expirata. Ruleaza din nou `python3 run.py --login`.

## Import din exportul platformei (varianta de rezerva)

Merge fara niciun browser si fara login, si e singura cale de a aduce metricile
private (reach, impresii):

- **Meta Business Suite** -> Content -> *Export Data* -> CSV (Instagram si Facebook).
- **TikTok Studio** -> *Download data* -> CSV/XLSX.

Din **Setari -> Import din export**: alegi clientul si contul, urci fisierul,
aplicatia ghiceste ce inseamna fiecare coloana (recunoaste denumiri uzuale ca
"Post ID", "Publish Time", "Video views"), tu confirmi, si maparea se retine
pentru data viitoare. Daca platforma redenumeste o coloana, o corectezi din
interfata, fara modificare de cod.

## Cum se numara planul

Planul se pune pe **client**, nu pe platforma, pentru ca acelasi material publicat
pe Instagram, Facebook si TikTok e o singura bucata de continut, nu trei.
Aplicatia grupeaza singura postarile: se uita la textul postarii (ignorand
hashtaguri, linkuri si emoji) si la cat de apropiate sunt in timp.

Se pot pune:

- tinte **pe saptamana** si **pe luna**, simultan (ex. 4 postari/saptamana *si*
  10 videoclipuri/luna);
- tinte **cu interval**, cand contractul spune "2-3 video pe saptamana" - se
  bifeaza ca realizate la minimul intervalului;
- tinte **separate pe o platforma anume**, daca chiar ai nevoie (sectiunea
  optionala din Setari > Plan) - acolo se numara fiecare postare in parte.

Un plan ramane valabil in fiecare saptamana/luna pana il schimbi.

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
    scraper/               sincronizare automata prin browserul tau
      browser.py           Playwright, profil persistent, dump de diagnosticare
      platforms.py         recunoasterea postarilor in JSON-ul fiecarei retele
      parse.py             helperi puri de extractie (testabili fara retea)
    csvfile.py             import generic, condus de mapare de coloane
    presets.py             ghicirea denumirilor de coloane (Meta/TikTok/RO)
    internal_csv.py        import/export in formatul propriu al aplicatiei
    graph.py               sincronizare optionala prin Meta Graph API
    aggregator.py          stub pentru un agregator platit (Ayrshare etc.)
web/                       interfata (HTML/CSS/JS, fara framework)
tests/                     teste (python3 -m unittest discover tests)
```

## Teste

```bash
python3 -m unittest discover tests -v
```

## Extindere viitoare

- Daca numarul de conturi creste mult si intretinerea scraperului devine
  suparatoare, un agregator platit (Ayrshare, Phyllo) rezolva acelasi lucru
  contra cost - vezi `tracker/sources/aggregator.py` pentru unde s-ar conecta.
- Adaptorul Graph API (`tracker/sources/graph.py`) e gata de folosit daca faci
  vreodata App Review la Meta; atunci ai si metricile private, automat.

## De retinut

Scraperul e gandit pentru paginile pe care le administrezi, rulat local, la
volum mic. Nu il folosi pe conturi straine si nu-l transforma intr-o colectare
masiva de date - si pentru ca nu e treaba lui, si pentru ca asa ramane sub
radarul limitelor de trafic ale platformelor.
