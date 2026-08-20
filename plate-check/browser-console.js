/*
 * Verifica statusul placutelor MS01WWW .. MS99WWW pe drpciv.
 *
 * Cum se ruleaza:
 *   1. Deschide https://dgpci.mai.gov.ro/ si mergi pe formularul de verificare placute.
 *   2. F12 -> Console. Lipeste tot fisierul asta, Enter.
 *   3. Ruleaza:  await runAll()
 *
 * Detecteaza singur varianta de reCAPTCHA:
 *   v3 -> ia site key-ul din api.js?render=... si cauta actiunea in bundle
 *   v2 -> randeaza un widget invizibil cu site key-ul lor si ia token din el
 * Daca se impotmoleste, ruleaza diagnose().
 *
 * Progresul se salveaza dupa fiecare placuta. Daca se intrerupe (inchizi tabul,
 * browserul incetineste timerele), lipesti scriptul din nou si dai iar runAll() -
 * continua de unde a ramas, nu reia de la capat.
 */

(function () {

const CONFIG = {
  endpoint: 'https://dgpci.mai.gov.ro/drpciv-forms-api/plate-status',
  prefix: 'MS',
  suffix: 'WWW',
  from: 1,
  to: 99,
  language: 'RO',
  userEmail: '',
  // Pauza intre cereri (ms). Nu cobori sub ~1500 - e un API public al statului.
  delayMs: 2500,
  retryDelayMs: 8000,
  maxRetries: 2,
  storageKey: 'plateCheck.results',
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ------------------------------------------------------------------ *
 * Captura automata a parametrilor reCAPTCHA
 * ------------------------------------------------------------------ */

/*
 * In loc sa ghicim parametrii reCAPTCHA, ne punem un wrapper peste
 * grecaptcha.execute / grecaptcha.render si lasam site-ul sa ne spuna singur ce
 * foloseste: la prima verificare manuala din formular, interceptam argumentele.
 *
 * Acoperim doua variante:
 *   v3 / Enterprise  ->  execute(siteKey, { action })  returneaza direct tokenul
 *   v2 invizibil     ->  render(...) da un widgetId; execute(widgetId) porneste
 *                        verificarea, iar tokenul se citeste cu getResponse()
 *
 * Starea sta pe window, nu in closure: daca scriptul e lipit de mai multe ori in
 * aceeasi pagina, patch-ul pus de prima copie trebuie sa scrie intr-un obiect pe
 * care il vad si copiile urmatoare.
 */
const captured = window.__plateCheckCaptured ||
  (window.__plateCheckCaptured = {
    siteKey: null, action: null, widgetId: null,
    execute: null, reset: null,
  });

/** API-ul reCAPTCHA folosit de pagina (Enterprise daca exista, altfel clasic). */
function recaptchaApi() {
  return (window.grecaptcha && window.grecaptcha.enterprise) || window.grecaptcha || null;
}

function armCapture() {
  // Patchuim ambele obiecte: unele pagini au si grecaptcha, si
  // grecaptcha.enterprise, si nu stim pe care il apeleaza aplicatia.
  const targets = [window.grecaptcha, window.grecaptcha && window.grecaptcha.enterprise];
  let armed = false;

  for (const api of targets) {
    if (!api || typeof api.execute !== 'function') continue;
    armed = true;
    if (api.execute.__patched) continue;

    // Pastram referintele nepatchuite: cererile noastre le folosesc direct, ca
    // sa nu ne interceptam singuri apelurile si sa poluam captura.
    const originalExecute = api.execute.bind(api);
    if (!captured.execute) captured.execute = originalExecute;
    if (!captured.reset && typeof api.reset === 'function') captured.reset = api.reset.bind(api);

    const executeWrapper = function (first, opts) {
      const action = opts && opts.action;
      if (typeof first === 'string' && first.startsWith('6')) {
        const isNew = first !== captured.siteKey || action !== captured.action;
        captured.siteKey = first;
        if (action) captured.action = action;
        if (isNew) {
          console.log('%cCaptat (v3):', 'color:#0a0;font-weight:bold',
            `siteKey=${first}`, `action=${captured.action}`);
        }
      } else if (first !== undefined && captured.widgetId !== first) {
        captured.widgetId = first;
        console.log('%cCaptat (v2):', 'color:#0a0;font-weight:bold', `widgetId=${first}`);
      }
      return originalExecute(first, opts);
    };
    executeWrapper.__patched = true;
    api.execute = executeWrapper;

    if (typeof api.render === 'function' && !api.render.__patched) {
      const originalRender = api.render.bind(api);
      if (!captured.render) captured.render = originalRender;
      const renderWrapper = function (container, params) {
        const widgetId = originalRender(container, params);
        if (params && params.sitekey) {
          captured.siteKey = captured.siteKey || params.sitekey;
          captured.widgetId = widgetId;
          console.log('%cCaptat (render):', 'color:#0a0;font-weight:bold',
            `siteKey=${params.sitekey}`, `widgetId=${widgetId}`, `size=${params.size}`);
        }
        return widgetId;
      };
      renderWrapper.__patched = true;
      api.render = renderWrapper;
    }
  }

  return armed;
}

/*
 * Fallback cand hookul nu prinde niciodata: aplicatiile Angular isi tin de
 * obicei o referinta la execute de la incarcare, dinainte sa apucam noi sa
 * punem wrapperul, asa ca apelul nu mai trece prin el. Atunci cautam actiunea
 * direct in bundle-urile lor - sunt same-origin, deci le putem citi.
 */
async function findActionsInBundles() {
  const urls = [...document.querySelectorAll('script[src]')]
    .map((s) => s.src)
    .filter((u) => { try { return new URL(u).origin === location.origin; } catch { return false; } });

  const found = new Set();

  for (const url of urls) {
    let text;
    try { text = await (await fetch(url)).text(); }
    catch { continue; }

    // execute(<ceva>, { action: "..." })  - forma cea mai sigura
    for (const m of text.matchAll(/execute\s*\([^,()]{0,80},\s*\{\s*action\s*:\s*["'`]([\w.\-\/]+)["'`]/g)) {
      found.add(m[1]);
    }
    // orice { action: "..." } - mai zgomotos, il punem dupa
    for (const m of text.matchAll(/\baction\s*:\s*["'`]([\w.\-\/]{3,40})["'`]/g)) {
      found.add(m[1]);
    }
  }

  const list = [...found];
  console.log(`Actiuni gasite in bundle: ${list.length ? list.join(', ') : '(niciuna)'}`);
  return list;
}

/** Site key-ul se poate afla si din DOM, fara verificare manuala. Actiunea nu. */
function sniffSiteKey() {
  const el = document.querySelector('[data-sitekey]');
  if (el) return el.getAttribute('data-sitekey');

  // Iframe-ul reCAPTCHA are site key-ul in query string: .../anchor?ar=1&k=6Le...
  for (const f of document.querySelectorAll('iframe[src*="recaptcha"]')) {
    try {
      const k = new URL(f.src).searchParams.get('k');
      if (k) return k;
    } catch { /* src invalid, ignoram */ }
  }

  for (const s of document.querySelectorAll('script[src*="recaptcha"]')) {
    const m = s.src.match(/[?&]render=([^&]+)/);
    if (m && m[1] !== 'explicit') return decodeURIComponent(m[1]);
  }
  return null;
}

/*
 * v3 vs v2. Semnul decisiv e cum a fost incarcat api.js:
 *   ?render=<sitekey>  -> v3, cheia e inregistrata, execute(key, {action}) merge
 *   fara render=       -> v2, cheia traieste intr-un widget, iar execute(key, ...)
 *                         da "Invalid site key or not loaded in api.js"
 */
function detectMode() {
  for (const el of document.querySelectorAll('script[src*="recaptcha"]')) {
    const m = el.src.match(/[?&]render=([^&]+)/);
    if (m && m[1] !== 'explicit') return 'v3';
  }
  const api = recaptchaApi();
  if (api && typeof api.getResponse === 'function' && typeof api.render === 'function') return 'v2';
  return 'necunoscut';
}

/*
 * La v2 nu exista actiuni: tokenul vine dintr-un widget. Daca pagina nu ne da
 * unul (nu a randat inca, sau apelurile ei nu trec prin hook), ne randam noi
 * unul invizibil, ascuns, cu site key-ul lor - acelasi mecanism, aceeasi cheie.
 */
function ensureWidget() {
  if (captured.widgetId !== null) return captured.widgetId;

  const api = recaptchaApi();
  const siteKey = captured.siteKey || sniffSiteKey();
  if (!siteKey) throw new Error('Nu am site key pentru widget.');
  if (!api || typeof api.render !== 'function') throw new Error('grecaptcha.render lipseste.');

  let host = document.getElementById('plateCheckCaptchaHost');
  if (!host) {
    host = document.createElement('div');
    host.id = 'plateCheckCaptchaHost';
    host.style.cssText =
      'position:fixed;bottom:0;right:0;width:1px;height:1px;opacity:0;pointer-events:none;';
    document.body.appendChild(host);
  }

  const render = captured.render || api.render.bind(api);
  captured.widgetId = render(host, { sitekey: siteKey, size: 'invisible', callback: () => {} });
  console.log(`Widget propriu randat: widgetId=${captured.widgetId} siteKey=${siteKey}`);
  return captured.widgetId;
}

/** Ce fel de reCAPTCHA e in pagina - util cand captura nu prinde. */
function diagnose() {
  const api = recaptchaApi();
  const frames = [...document.querySelectorAll('iframe[src*="recaptcha"]')].map((f) => {
    try {
      const u = new URL(f.src);
      return { path: u.pathname, k: u.searchParams.get('k'), size: u.searchParams.get('size') };
    } catch { return { src: f.src }; }
  });

  const info = {
    grecaptcha: !!window.grecaptcha,
    enterprise: !!(window.grecaptcha && window.grecaptcha.enterprise),
    metode: api ? Object.keys(api).filter((k) => typeof api[k] === 'function') : [],
    iframes: frames,
    varianta: detectMode(),
    elementDataSitekey: !!document.querySelector('[data-sitekey]'),
    siteKeyGasit: captured.siteKey || sniffSiteKey(),
    actiuneCaptata: captured.action,
    widgetId: captured.widgetId,
    hookActiv: !!(window.grecaptcha && window.grecaptcha.execute && window.grecaptcha.execute.__patched),
    hookActivEnterprise: !!(window.grecaptcha && window.grecaptcha.enterprise &&
      window.grecaptcha.enterprise.execute && window.grecaptcha.enterprise.execute.__patched),
  };
  console.log('%cDiagnostic reCAPTCHA', 'color:#06c;font-weight:bold');
  console.log(info);
  console.log(
    info.varianta === 'v3'
      ? 'reCAPTCHA v3 (execute cu actiune).'
      : info.varianta === 'v2'
        ? 'reCAPTCHA v2 (widget; actiunile nu se aplica).'
        : 'Varianta neclara - grecaptcha poate nu s-a incarcat complet.'
  );
  return info;
}

async function getToken(actionOverride) {
  const api = recaptchaApi();
  if (!api) throw new Error('grecaptcha nu e incarcat in pagina.');
  await new Promise((resolve) => api.ready(resolve));

  const execute = captured.execute || api.execute.bind(api);
  const action = actionOverride || captured.action;

  // v3: tokenul vine direct din promisiune.
  if (detectMode() === 'v3' && captured.siteKey && action) {
    return execute(captured.siteKey, { action });
  }

  // v2: pornim widgetul si asteptam sa apara raspunsul.
  const widgetId = ensureWidget();
  const reset = captured.reset || (typeof api.reset === 'function' ? api.reset.bind(api) : null);
  if (reset) reset(widgetId);
  execute(widgetId);

  const deadline = Date.now() + 30000;
  for (;;) {
    const token = api.getResponse(widgetId);
    if (token) return token;
    if (Date.now() > deadline) {
      throw new Error(
        'Timeout la reCAPTCHA v2 - widgetul nu a produs token in 30s. ' +
        'Daca cheia lor cere bifa umana la fiecare verificare, rularea in lot nu e posibila.'
      );
    }
    await sleep(300);
  }
}

/* ------------------------------------------------------------------ *
 * Cererea
 * ------------------------------------------------------------------ */

function buildPlates() {
  const plates = [];
  for (let i = CONFIG.from; i <= CONFIG.to; i++) {
    plates.push(`${CONFIG.prefix}${String(i).padStart(2, '0')}${CONFIG.suffix}`);
  }
  return plates;
}

async function checkPlate(plateNumber, action) {
  const res = await fetch(CONFIG.endpoint, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({
      plateNumber,
      userEmail: CONFIG.userEmail,
      language: CONFIG.language,
      reCaptchaKey: await getToken(action),
    }),
  });

  const text = await res.text();
  let body;
  try { body = JSON.parse(text); } catch { body = text; }

  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

/* ------------------------------------------------------------------ *
 * Progres persistent
 * ------------------------------------------------------------------ */

function load() {
  try { return JSON.parse(localStorage.getItem(CONFIG.storageKey)) || {}; }
  catch { return {}; }
}

function save(store) {
  try { localStorage.setItem(CONFIG.storageKey, JSON.stringify(store)); }
  catch (e) { console.warn('Nu pot salva progresul:', e.message); }
}

function remaining() {
  const store = load();
  return buildPlates().filter((p) => !store[p] || store[p].ok === false);
}

/* ------------------------------------------------------------------ *
 * Rulare
 * ------------------------------------------------------------------ */

/** Actiunile plauzibile primele, ca sa nimerim din prima incercare. */
function rankActions(list) {
  const scor = (a) => {
    const x = a.toLowerCase();
    if (/plate|placu|numar/.test(x)) return 0;
    if (/status|verif|check|search/.test(x)) return 1;
    if (/submit|form/.test(x)) return 2;
    return 3;
  };
  return [...list].sort((a, b) => scor(a) - scor(b)).slice(0, 8);
}

/*
 * Cand nu stim actiunea, o deducem incercand candidatii pe o singura placuta.
 * Costa cel mult cateva cereri, nu 99, si se opreste la prima care trece.
 */
async function resolveAction(candidates, plate) {
  console.log(`Incerc sa deduc actiunea reCAPTCHA pe ${plate}: ${candidates.join(', ')}`);

  for (const action of candidates) {
    try {
      const body = await checkPlate(plate, action);
      console.log(`%cActiunea corecta: ${action}`, 'color:#0a0;font-weight:bold');
      return { action, body };
    } catch (e) {
      console.warn(`  ${action} -> respins (${e.message})`);
      await sleep(CONFIG.delayMs);
    }
  }

  console.error(
    'Niciun candidat nu a fost acceptat.\nRuleaza diagnose() si trimite ce afiseaza.'
  );
  return null;
}

async function runAll(opts = {}) {
  armCapture();

  if (!captured.siteKey) captured.siteKey = sniffSiteKey();
  if (opts.action) captured.action = opts.action;

  // Varianta decide tot: la v2 nu exista actiuni, deci nici nu le cautam.
  const mode = detectMode();
  const v2 = mode !== 'v3';
  console.log(`Varianta reCAPTCHA: ${mode}`);

  let candidates = [];
  if (!v2 && !captured.action && captured.siteKey) {
    candidates = rankActions(await findActionsInBundles());
  }

  if (!captured.siteKey) {
    console.warn(
      '%cNu gasesc site key-ul reCAPTCHA.', 'color:#c00;font-weight:bold',
      '\nEsti pe pagina formularului de verificare placute? Ruleaza diagnose().'
    );
    return;
  }

  if (!captured.action && !v2 && !candidates.length) {
    console.warn(
      '%cNu am actiunea reCAPTCHA.', 'color:#c00;font-weight:bold',
      '\nVerifica o placuta manual din formular (poate o prinde hookul),' +
      '\nsau dai direct:  await runAll({ action: "numele_actiunii" })' +
      '\nRuleaza diagnose() ca sa vezi ce e in pagina.'
    );
    return;
  }

  const todo = remaining();
  const total = buildPlates().length;

  if (!todo.length) {
    console.log(`Toate cele ${total} sunt deja verificate. downloadCsv() sau reset() ca sa o iei de la capat.`);
    return load();
  }

  console.log(`De verificat: ${todo.length} din ${total} (restul sunt deja salvate).`);

  if (!captured.action && !v2) {
    const rezolvat = await resolveAction(candidates, todo[0]);
    if (!rezolvat) return;

    captured.action = rezolvat.action;
    const store = load();
    store[todo[0]] = { plate: todo[0], ok: true, response: rezolvat.body, at: Date.now() };
    save(store);
    todo.shift();
    if (!todo.length) { console.log('Gata, toate.'); return load(); }
    await sleep(CONFIG.delayMs);
  }

  console.log(`siteKey=${captured.siteKey} action=${captured.action} widgetId=${captured.widgetId}`);

  for (let i = 0; i < todo.length; i++) {
    const plate = todo[i];
    const store = load();
    let attempt = 0;

    for (;;) {
      try {
        const body = await checkPlate(plate, captured.action);
        store[plate] = { plate, ok: true, response: body, at: Date.now() };
        save(store);
        console.log(`[${i + 1}/${todo.length}] ${plate}`, body);
        break;
      } catch (e) {
        attempt++;

        // Daca prima placuta pica pe captcha, parametrii sunt gresiti -
        // ne oprim imediat in loc sa batem degeaba in API 99 de ori.
        const looksLikeCaptcha =
          e.status === 400 || e.status === 403 ||
          /captcha/i.test(JSON.stringify(e.body || ''));

        if (i === 0 && looksLikeCaptcha) {
          console.error(
            'Prima cerere a fost respinsa - foarte probabil actiunea reCAPTCHA e gresita.' +
            '\nVerifica o placuta manual din formular ca scriptul sa recaptureze, apoi runAll().',
            e.body
          );
          return;
        }

        if (attempt > CONFIG.maxRetries) {
          store[plate] = { plate, ok: false, error: String(e), body: e.body, at: Date.now() };
          save(store);
          console.warn(`[${i + 1}/${todo.length}] ${plate} EROARE`, e.body || e);
          break;
        }
        console.warn(`${plate}: incercarea ${attempt} a esuat (${e.message}), reincerc...`);
        await sleep(CONFIG.retryDelayMs);
      }
    }

    if (i < todo.length - 1) await sleep(CONFIG.delayMs);
  }

  const left = remaining();
  console.log(left.length ? `Gata, dar au ramas ${left.length} cu erori. Ruleaza iar runAll().` : 'Gata, toate.');
  console.table(Object.values(load()).map(flatten));
  return load();
}

function progres() {
  const store = load();
  const done = Object.values(store).filter((r) => r.ok).length;
  const failed = Object.values(store).filter((r) => !r.ok).length;
  console.log(`Salvate: ${done} reusite, ${failed} cu eroare, ${remaining().length} ramase.`);
  return { done, failed, remaining: remaining() };
}

function reset() {
  localStorage.removeItem(CONFIG.storageKey);
  console.log('Progres sters.');
}

/* ------------------------------------------------------------------ *
 * Export
 * ------------------------------------------------------------------ */

function flatten(r) {
  const out = { plate: r.plate, ok: r.ok };
  if (r.response && typeof r.response === 'object') {
    for (const [k, v] of Object.entries(r.response)) {
      out[k] = (v && typeof v === 'object') ? JSON.stringify(v) : v;
    }
  } else if (r.response !== undefined) {
    out.response = r.response;
  }
  if (!r.ok) out.error = r.error;
  return out;
}

function download(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

function sortedResults() {
  const store = load();
  return buildPlates().filter((p) => store[p]).map((p) => store[p]);
}

function downloadCsv(filename = 'plate-status.csv') {
  const rows = sortedResults().map(flatten);
  if (!rows.length) return console.warn('Nu exista rezultate. Ruleaza intai: await runAll()');
  const cols = [...new Set(rows.flatMap(Object.keys))];
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const csv = [cols.join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n');
  download(filename, csv, 'text/csv;charset=utf-8');
}

function downloadJson(filename = 'plate-status.json') {
  const rows = sortedResults();
  if (!rows.length) return console.warn('Nu exista rezultate. Ruleaza intai: await runAll()');
  download(filename, JSON.stringify(rows, null, 2), 'application/json');
}

/* ------------------------------------------------------------------ *
 * Expunere in consola
 * ------------------------------------------------------------------ */

Object.assign(window, { runAll, progres, reset, downloadCsv, downloadJson, diagnose, findActionsInBundles });
window.plateCheck = { CONFIG, captured, remaining, buildPlates };

/* ------------------------------------------------------------------ */

if (armCapture()) {
  console.log(
    '%cIncarcat.', 'color:#0a0;font-weight:bold',
    '\n\nRuleaza direct:  await runAll()' +
    '\nDetecteaza singur daca e reCAPTCHA v2 sau v3 si isi ia parametrii.' +
    '\n\nDaca se plange ca nu le gaseste, verifica o placuta manual din formular' +
    '\n(hookul o prinde), sau forteaza:  await runAll({ action: "..." })' +
    '\n\nAltele:  diagnose()  progres()  downloadCsv()  downloadJson()  reset()'
  );
} else {
  console.warn('grecaptcha nu e in pagina. Esti pe formularul de verificare placute?');
}

})();
