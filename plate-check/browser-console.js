/*
 * Verifica statusul placutelor MS01WWW .. MS99WWW pe drpciv.
 *
 * Cum se ruleaza:
 *   1. Deschide https://dgpci.mai.gov.ro/ si mergi pe formularul de verificare placute.
 *   2. Deschide DevTools -> Console (F12).
 *   3. Lipeste tot fisierul asta si apasa Enter.
 *   4. Ruleaza:  await runAll()
 *
 * Trebuie rulat din pagina site-ului: altfel cererea e cross-origin si
 * nu ai acces la obiectul grecaptcha pentru a genera token-uri noi.
 */

const CONFIG = {
  endpoint: 'https://dgpci.mai.gov.ro/drpciv-forms-api/plate-status',
  prefix: 'MS',
  suffix: 'WWW',
  from: 1,
  to: 99,
  language: 'RO',
  userEmail: '',
  // Actiunea reCAPTCHA folosita de site. Daca primesti eroare de captcha,
  // vezi README pentru cum afli valoarea corecta.
  recaptchaAction: 'submit',
  // Pauza intre cereri (ms). Nu cobori sub ~1500 - e un API public al statului,
  // nu are rost sa il bombardezi.
  delayMs: 2500,
  // Pauza suplimentara dupa o eroare, inainte de retry.
  retryDelayMs: 8000,
  maxRetries: 2,
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Construieste lista MS01WWW ... MS99WWW (numarul e mereu pe 2 cifre). */
function buildPlates() {
  const plates = [];
  for (let i = CONFIG.from; i <= CONFIG.to; i++) {
    plates.push(`${CONFIG.prefix}${String(i).padStart(2, '0')}${CONFIG.suffix}`);
  }
  return plates;
}

/** Gaseste site key-ul reCAPTCHA incarcat de pagina. */
function findSiteKey() {
  const el = document.querySelector('[data-sitekey]');
  if (el) return el.getAttribute('data-sitekey');

  for (const s of document.querySelectorAll('script[src*="recaptcha"]')) {
    const m = s.src.match(/[?&]render=([^&]+)/);
    if (m && m[1] !== 'explicit') return decodeURIComponent(m[1]);
  }

  const cfg = window.___grecaptcha_cfg;
  if (cfg && cfg.clients) {
    for (const client of Object.values(cfg.clients)) {
      const found = deepFindSiteKey(client, 0);
      if (found) return found;
    }
  }
  throw new Error('Nu am gasit site key-ul reCAPTCHA. Esti pe pagina formularului?');
}

function deepFindSiteKey(obj, depth) {
  if (depth > 4 || !obj || typeof obj !== 'object') return null;
  for (const v of Object.values(obj)) {
    if (typeof v === 'string' && /^6[0-9A-Za-z_-]{38,}$/.test(v)) return v;
    const nested = deepFindSiteKey(v, depth + 1);
    if (nested) return nested;
  }
  return null;
}

/** Cere un token nou de la reCAPTCHA - unul singur, valabil o singura data. */
async function getToken(siteKey) {
  const api = (window.grecaptcha && window.grecaptcha.enterprise) || window.grecaptcha;
  if (!api) throw new Error('grecaptcha nu e incarcat in pagina.');
  await new Promise((resolve) => api.ready(resolve));
  return api.execute(siteKey, { action: CONFIG.recaptchaAction });
}

async function checkPlate(plateNumber, siteKey) {
  const res = await fetch(CONFIG.endpoint, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      plateNumber,
      userEmail: CONFIG.userEmail,
      language: CONFIG.language,
      reCaptchaKey: await getToken(siteKey),
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

const results = [];

async function runAll() {
  const siteKey = findSiteKey();
  const plates = buildPlates();
  console.log(`Site key: ${siteKey}`);
  console.log(`Verific ${plates.length} placute (${plates[0]} -> ${plates[plates.length - 1]})`);

  results.length = 0;

  for (let i = 0; i < plates.length; i++) {
    const plate = plates[i];
    let attempt = 0;

    for (;;) {
      try {
        const body = await checkPlate(plate, siteKey);
        results.push({ plate, ok: true, response: body });
        console.log(`[${i + 1}/${plates.length}] ${plate}`, body);
        break;
      } catch (e) {
        attempt++;
        if (attempt > CONFIG.maxRetries) {
          results.push({ plate, ok: false, error: String(e), body: e.body });
          console.warn(`[${i + 1}/${plates.length}] ${plate} EROARE`, e.body || e);
          break;
        }
        console.warn(`${plate}: incercarea ${attempt} a esuat (${e.message}), reincerc...`);
        await sleep(CONFIG.retryDelayMs);
      }
    }

    if (i < plates.length - 1) await sleep(CONFIG.delayMs);
  }

  console.log('Gata.');
  console.table(results.map(flatten));
  return results;
}

/** Aplatizeaza raspunsul ca sa se vada frumos in console.table / CSV. */
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

/** Descarca rezultatele ca CSV. */
function downloadCsv(filename = 'plate-status.csv') {
  if (!results.length) return console.warn('Nu exista rezultate. Ruleaza intai: await runAll()');
  const rows = results.map(flatten);
  const cols = [...new Set(rows.flatMap(Object.keys))];
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const csv = [cols.join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n');

  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

/** Descarca rezultatele brute ca JSON. */
function downloadJson(filename = 'plate-status.json') {
  if (!results.length) return console.warn('Nu exista rezultate. Ruleaza intai: await runAll()');
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' })
  );
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

console.log('Incarcat. Ruleaza:  await runAll()   apoi:  downloadCsv()  /  downloadJson()');
