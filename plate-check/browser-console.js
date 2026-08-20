/*
 * Verifica statusul placutelor MS01WWW .. MS99WWW pe drpciv.
 *
 * Cum se ruleaza:
 *   1. Deschide https://dgpci.mai.gov.ro/ si mergi pe formularul de verificare placute.
 *   2. F12 -> Console. Lipeste tot fisierul asta, Enter.
 *   3. Verifica O SINGURA placuta manual, din formular. Scriptul intercepteaza
 *      apelul si retine singur site key-ul + actiunea reCAPTCHA.
 *   4. Ruleaza:  await runAll()
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
 * In loc sa ghicim actiunea reCAPTCHA, ne punem un wrapper peste
 * grecaptcha.execute si lasam site-ul sa ne spuna singur ce foloseste:
 * la prima verificare manuala din formular, interceptam argumentele reale.
 */
/*
 * Starea capturii sta pe window, nu in closure: daca scriptul e lipit de mai
 * multe ori in aceeasi pagina, patch-ul pus de prima copie trebuie sa scrie
 * intr-un obiect pe care il vad si copiile urmatoare.
 */
const captured = window.__plateCheckCaptured ||
  (window.__plateCheckCaptured = { siteKey: null, action: null, execute: null });

/** API-ul reCAPTCHA folosit de pagina (Enterprise daca exista, altfel clasic). */
function recaptchaApi() {
  return (window.grecaptcha && window.grecaptcha.enterprise) || window.grecaptcha || null;
}

function armCapture() {
  const api = recaptchaApi();
  if (!api || typeof api.execute !== 'function') return false;
  if (api.execute.__patched) return true;

  // Pastram referinta nepatchuita: cererile noastre o folosesc direct, ca sa nu
  // ne interceptam singuri apelurile si sa poluam captura.
  const original = api.execute.bind(api);
  captured.execute = original;

  const wrapper = function (siteKey, opts) {
    const action = opts && opts.action;
    if (typeof siteKey === 'string' && siteKey.startsWith('6')) {
      const isNew = siteKey !== captured.siteKey || action !== captured.action;
      captured.siteKey = siteKey;
      if (action) captured.action = action;
      if (isNew) {
        console.log('%cCaptat:', 'color:#0a0;font-weight:bold',
          `siteKey=${siteKey}`, `action=${captured.action}`);
      }
    }
    return original(siteKey, opts);
  };
  wrapper.__patched = true;
  api.execute = wrapper;
  return true;
}

/** Site key-ul se poate afla si din DOM, fara verificare manuala. Actiunea nu. */
function sniffSiteKey() {
  const el = document.querySelector('[data-sitekey]');
  if (el) return el.getAttribute('data-sitekey');

  for (const s of document.querySelectorAll('script[src*="recaptcha"]')) {
    const m = s.src.match(/[?&]render=([^&]+)/);
    if (m && m[1] !== 'explicit') return decodeURIComponent(m[1]);
  }
  return null;
}

async function getToken() {
  const api = recaptchaApi();
  if (!api) throw new Error('grecaptcha nu e incarcat in pagina.');
  await new Promise((resolve) => api.ready(resolve));
  const execute = captured.execute || api.execute.bind(api);
  return execute(captured.siteKey, { action: captured.action });
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

async function checkPlate(plateNumber) {
  const res = await fetch(CONFIG.endpoint, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({
      plateNumber,
      userEmail: CONFIG.userEmail,
      language: CONFIG.language,
      reCaptchaKey: await getToken(),
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

async function runAll() {
  armCapture();

  if (!captured.siteKey) captured.siteKey = sniffSiteKey();

  if (!captured.siteKey || !captured.action) {
    console.warn(
      '%cLipsesc parametrii reCAPTCHA.',
      'color:#c00;font-weight:bold',
      '\nVerifica O SINGURA placuta manual, din formularul paginii.' +
      '\nScriptul prinde singur site key-ul si actiunea, apoi dai din nou: await runAll()'
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
  console.log(`siteKey=${captured.siteKey} action=${captured.action}`);

  for (let i = 0; i < todo.length; i++) {
    const plate = todo[i];
    const store = load();
    let attempt = 0;

    for (;;) {
      try {
        const body = await checkPlate(plate);
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

Object.assign(window, { runAll, progres, reset, downloadCsv, downloadJson });
window.plateCheck = { CONFIG, captured, remaining, buildPlates };

/* ------------------------------------------------------------------ */

if (armCapture()) {
  console.log(
    '%cIncarcat.', 'color:#0a0;font-weight:bold',
    '\n1. Verifica o placuta manual din formular (o singura data) - ca sa captez parametrii reCAPTCHA.' +
    '\n2. Apoi:  await runAll()' +
    '\n\nAltele:  progres()  downloadCsv()  downloadJson()  reset()'
  );
} else {
  console.warn('grecaptcha nu e in pagina. Esti pe formularul de verificare placute?');
}

})();
