# Verificare status placute MS01WWW - MS99WWW

Script pentru interogarea endpointului public
`POST https://dgpci.mai.gov.ro/drpciv-forms-api/plate-status`
pentru toate placutele din intervalul `MS01WWW` ... `MS99WWW`.

## De ce trebuie rulat din browserul tau

Payload-ul contine `reCaptchaKey` - un token reCAPTCHA Enterprise care este
de unica folosinta, expira in ~2 minute si e legat de originea paginii lor.
Deci un token copiat din DevTools iti da exact **un** raspuns valid; pentru 99
de placute ai nevoie de 99 de token-uri proaspete.

Singurul mod curat de a le obtine este sa lasi pagina sa le genereze - adica sa
rulezi din browserul tau, in sesiunea ta, de pe IP-ul tau. Un browser headless
pornit dintr-un server nu e o varianta: reCAPTCHA Enterprise scoreaza exact
tiparul ala drept bot, deci nici nu ar functiona.

## Utilizare

1. Deschide <https://dgpci.mai.gov.ro/> si navigheaza la formularul de
   verificare a placutei.
2. Deschide consola: **F12** (sau click dreapta -> *Inspect* / *Inspecteaza*),
   apoi tab-ul **Console**.
   Lipeste continutul din [`browser-console.js`](browser-console.js) si Enter.

   > Prima data cand lipesti ceva in consola, Chrome/Brave refuza si iti cere
   > sa scrii `allow pasting` + Enter. Scrii asta o data, apoi lipesti din nou.
3. Porneste:

   ```js
   await runAll()
   ```

4. Cand se termina, exporta:

   ```js
   downloadCsv()    // sau downloadJson()
   ```

Ruleaza secvential, cu 2.5s pauza intre cereri - deci ~4-5 minute pentru toate
cele 99.

## Cum isi gaseste parametrii reCAPTCHA

Nu trebuie sa cauti nimic manual. Primul lucru pe care il stabileste e
**varianta**, pentru ca de ea depinde tot restul. Semnul decisiv e cum a fost
incarcat `api.js`:

| incarcare | varianta | cum se obtine tokenul |
|---|---|---|
| `api.js?render=<sitekey>` | v3 | `execute(sitekey, { action })` |
| `api.js` simplu | v2 | un widget; `execute(widgetId)` + `getResponse()` |

**La v3** ia site key-ul din parametrul `render=`, apoi cauta actiunea in
bundle-urile same-origin ale paginii, pune candidatii plauzibili primii si
confirma alegerea incercand-o pe o singura placuta - cateva cereri, nu 99.

**La v2 nu exista actiuni.** Site key-ul vine din elementul `[data-sitekey]` sau
din iframeul reCAPTCHA, iar tokenul dintr-un widget: daca pagina nu ne da unul,
scriptul randeaza el unul invizibil, ascuns, cu site key-ul lor - acelasi
mecanism si aceeasi cheie ca formularul.

Daca cheia lor e de tip v2 cu bifa care cere click uman la fiecare verificare,
rularea in lot pur si simplu nu e posibila; scriptul da timeout cu mesaj clar,
in loc sa insiste degeaba.

`diagnose()` afiseaza varianta detectata, site key-ul, iframeurile, si daca
hookul e activ.

## Se poate relua

Progresul se salveaza in `localStorage` dupa fiecare placuta. Daca inchizi
tabul, pica reteaua, sau browserul incetineste timerele pentru ca tabul a stat
prea mult in fundal, lipesti scriptul din nou si dai iar `runAll()`: continua
de unde a ramas si reincearca doar placutele esuate. Nu reia de la capat si nu
trimite cereri duplicate.

Nu mai conteaza deci daca tabul sta vizibil sau nu - in cel mai rau caz reiei.
Scriptul poate fi lipit de oricate ori in aceeasi pagina, nu se incurca singur.

## Comenzi

| comanda | ce face |
|---|---|
| `await runAll()` | ruleaza / continua verificarea |
| `await runAll({action:'x'})` | forteaza o anumita actiune reCAPTCHA |
| `diagnose()` | ce reCAPTCHA e in pagina si ce parametri s-au gasit |
| `progres()` | cate sunt gata, cate au esuat, cate au ramas |
| `downloadCsv()` | exporta rezultatele ca CSV |
| `downloadJson()` | exporta raspunsurile brute |
| `reset()` | sterge progresul salvat |

## Configurare

Editeaza `CONFIG` din capul fisierului:

| camp | default | ce face |
|---|---|---|
| `prefix` / `suffix` | `MS` / `WWW` | partile fixe ale placutei |
| `from` / `to` | `1` / `99` | intervalul numeric (formatat pe 2 cifre) |
| `delayMs` | `2500` | pauza intre cereri |
| `maxRetries` | `2` | reincercari per placuta |

## Daca nu merge

Ruleaza `diagnose()` - arata ce e in pagina. Cazuri uzuale:

- **`siteKeyGasit: null`** - nu esti pe pagina formularului, sau reCAPTCHA nu
  s-a incarcat inca. Asteapta sa se incarce complet si reia.
- **niciun candidat acceptat** - actiunea nu e in bundle sub o forma pe care o
  recunoaste regexul. Verifica o placuta manual din formular (poate o prinde
  hookul), altfel forteaz-o cu `runAll({ action: "..." })`.
- **In Brave**, `requestStorageAccess: Permission denied` in consola inseamna ca
  Shields blocheaza storage-ul pentru iframeul reCAPTCHA. De obicei merge
  oricum; daca nu, coboara Shields pentru site sau incearca in Chrome.

Scriptul se opreste la prima cerere respinsa, nu bate degeaba in API de 99 de ori.

## Forma cererii (referinta)

```json
{
  "plateNumber": "MS77WWW",
  "userEmail": "",
  "language": "RO",
  "reCaptchaKey": "0cAFcWeA..."
}
```

`single-request.sh` face un singur call cu un token dat manual - util ca sa
confirmi ca payload-ul si headerele sunt corecte.

## Nota

Endpointul e public, dar are rate limiting si protectie anti-bot. Scriptul
respecta asta: cereri secventiale, pauze intre ele, fara paralelism, si fara
ocolirea captchei - foloseste mecanismul paginii, nu il evita. Daca incepi sa
primesti `429`, opreste-te si mareste `delayMs`.
