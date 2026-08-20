# Verificare status placute MS01WWW - MS99WWW

Script pentru interogarea endpointului public
`POST https://dgpci.mai.gov.ro/drpciv-forms-api/plate-status`
pentru toate placutele din intervalul `MS01WWW` ... `MS99WWW`.

## De ce nu merge cu curl in bucla

Payload-ul contine `reCaptchaKey` - un token reCAPTCHA Enterprise care este:

- **de unica folosinta** - serverul il invalideaza dupa prima verificare;
- **cu expirare scurta** - ~2 minute;
- **legat de origine** - generat de pagina lor, pentru domeniul lor.

Deci un token copiat din DevTools iti da exact **un** raspuns valid. Pentru 99 de
placute ai nevoie de 99 de token-uri proaspete, iar singurul mod curat de a le
obtine este sa lasi pagina sa le genereze - adica sa rulezi din browserul tau,
in sesiunea ta.

## Utilizare

1. Deschide <https://dgpci.mai.gov.ro/> si navigheaza la formularul de verificare
   a placutei (acolo unde reCAPTCHA e deja incarcat in pagina).
2. F12 -> tab-ul **Console**.
3. Lipeste continutul din [`browser-console.js`](browser-console.js) si Enter.
4. Porneste:

   ```js
   await runAll()
   ```

5. Cand se termina, exporta:

   ```js
   downloadCsv()    // sau downloadJson()
   ```

Ruleaza secvential, cu 2.5s pauza intre cereri - deci ~4-5 minute pentru toate
cele 99. Nu lasa tabul in background prea agresiv (unele browsere throttle-uiesc
timerele); tine fereastra vizibila.

## Configurare

Editeaza obiectul `CONFIG` din capul fisierului:

| camp | default | ce face |
|---|---|---|
| `prefix` / `suffix` | `MS` / `WWW` | partile fixe ale placutei |
| `from` / `to` | `1` / `99` | intervalul numeric (formatat pe 2 cifre) |
| `delayMs` | `2500` | pauza intre cereri |
| `maxRetries` | `2` | reincercari per placuta |
| `recaptchaAction` | `submit` | actiunea trimisa la `grecaptcha.execute` |

### Daca primesti eroare de captcha

Cel mai probabil `recaptchaAction` nu corespunde. Afla valoarea reala asa:
in DevTools -> **Sources**, cauta in bundle-ul site-ului dupa `execute(` sau
`action:`; sirul din `{ action: '...' }` e ce trebuie pus in `CONFIG`.
Alternativ, pune un breakpoint pe `grecaptcha.enterprise.execute` si trimite o
data formularul manual ca sa vezi argumentele.

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
confirmi ca payload-ul si headerele sunt corecte inainte de a rula tot lotul.

## Nota

Endpointul e public, dar are rate limiting si protectie anti-bot. Scriptul
respecta asta: cereri secventiale, pauze intre ele, fara paralelism si fara
ocolirea captchei. Daca incepi sa primesti `429` sau erori repetate, opreste-te
si mareste `delayMs`.
