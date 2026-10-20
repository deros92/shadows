const DEFAULTS = { enabled: true, restore: 'safe', blockFiles: false, failMode: 'ask', service: 'http://127.0.0.1:8765' };
const $ = (id) => document.getElementById(id);
let lastDoc = null;

function bg(msg) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(msg, (resp) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resp && resp.ok ? resolve(resp.data) : reject(new Error(resp ? resp.error : 'nessuna risposta'));
    });
  });
}

async function loadSettings() {
  const s = { ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) };
  $('enabled').checked = s.enabled;
  // Le versioni precedenti salvavano un booleano.
  $('restore').value = s.restore === true ? 'safe' : s.restore === false ? 'off' : s.restore;
  $('blockFiles').checked = s.blockFiles;
  $('failMode').value = s.failMode;
  for (const id of ['enabled', 'blockFiles']) {
    $(id).addEventListener('change', () => chrome.storage.local.set({ [id]: $(id).checked }));
  }
  const warn = () => $('restorewarn').classList.toggle('hidden', $('restore').value !== 'dom');
  warn();
  for (const id of ['restore', 'failMode']) {
    $(id).addEventListener('change', () => { chrome.storage.local.set({ [id]: $(id).value }); warn(); });
  }
  return s;
}

const TRANSPORTS = { native: 'canale privato', http: 'porta locale 8765' };

async function checkHealth() {
  try {
    const h = await bg({ type: 'health' });
    if (h.status === 'loading') {
      // Shadows è appena stato avviato dal browser: il modello si sta caricando.
      $('status').textContent = 'avvio in corso: caricamento del modello…';
      $('status').className = 'status';
      setTimeout(checkHealth, 1500);
      return;
    }
    $('status').textContent = `attivo · v${h.version} · ${TRANSPORTS[h.transport] || h.transport}`;
    $('status').className = 'status ok';
    const dl = $('detectors');
    dl.replaceChildren();
    for (const [name, state] of Object.entries(h.detectors)) {
      const dt = document.createElement('dt');
      dt.textContent = name;
      const dd = document.createElement('dd');
      dd.textContent = state;
      dl.append(dt, dd);
    }
  } catch (err) {
    $('status').textContent = `non raggiungibile: ${err.message}. Registra Shadows con "python -m shadows install-native".`;
    $('status').className = 'status bad';
  }
}

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] || '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

$('file').addEventListener('change', async () => {
  const file = $('file').files[0];
  if (!file) return;
  $('docresult').classList.add('hidden');
  $('docmsg').textContent = `Analisi di ${file.name}…`;
  try {
    const tab = await activeTab();
    const scope = tab && tab.url ? new URL(tab.url).origin : 'popup';
    const known = await bg({ type: 'getMapping', scope });
    if (file.size > 20 * 1024 * 1024) throw new Error('file oltre 20 MB');
    const body = await bg({
      type: 'document', filename: file.name, data_b64: await readAsBase64(file),
      known, site: tab && tab.url ? new URL(tab.url).host : '',
    });

    lastDoc = body;
    const counts = {};
    for (const e of body.entities) counts[e.label] = (counts[e.label] || 0) + 1;
    const summary = Object.entries(counts).map(([k, v]) => `${k}×${v}`).join(', ') || 'nessuna entità';
    const warnings = body.document.warnings.length ? ` Attenzione: ${body.document.warnings.join(' ')}` : '';
    $('docmsg').textContent = `${body.document.kind.toUpperCase()}, ${body.document.chars} caratteri. Trovato: ${summary}. Decisione: ${body.action}.${warnings}`;
    $('doctext').value = body.action === 'block'
      ? 'Il documento contiene elementi che la policy non consente di inviare (es. credenziali).'
      : body.anonymized_text;
    $('insert').disabled = body.action === 'block';
    $('copy').disabled = body.action === 'block';
    $('docresult').classList.remove('hidden');
  } catch (err) {
    $('docmsg').textContent = `Errore: ${err.message}`;
  }
});

$('insert').addEventListener('click', async () => {
  if (!lastDoc) return;
  const tab = await activeTab();
  try {
    const resp = await chrome.tabs.sendMessage(tab.id, {
      type: 'insertDocument', text: lastDoc.anonymized_text, mapping: lastDoc.mapping,
    });
    $('docmsg').textContent = resp && resp.ok ? 'Inserito nella chat.' : `Non inserito: ${resp ? resp.error : 'scheda non supportata'}`;
  } catch {
    $('docmsg').textContent = 'Questa scheda non è una chat supportata: usa "Copia".';
  }
});

$('copy').addEventListener('click', async () => {
  if (!lastDoc) return;
  await navigator.clipboard.writeText(lastDoc.anonymized_text);
  // La mappa serve comunque per ripristinare i valori nella risposta.
  const tab = await activeTab();
  if (tab && tab.url) await bg({ type: 'saveMapping', scope: new URL(tab.url).origin, mapping: lastDoc.mapping });
  $('docmsg').textContent = 'Copiato negli appunti.';
});

// Riconversione manuale: funziona con qualunque sito e qualunque testo, perché usa
// la mappa della scheda attiva (in memoria, mai inviata al sito).
function restoreWith(text, mapping) {
  const names = Object.keys(mapping).map((ph) => ph.replace(/^\[|\]$/g, ''))
    .sort((a, b) => b.length - a.length);
  if (!names.length) return { text, n: 0 };
  const alt = names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  let n = 0;
  const out = text.replace(new RegExp(`\\[(${alt})\\]|\\b(${alt})\\b`, 'g'), (m, a, b) => {
    const value = mapping[`[${a || b}]`];
    if (value === undefined) return m;
    n += 1;
    return value;
  });
  return { text: out, n };
}

$('restorego').addEventListener('click', async () => {
  const tab = await activeTab();
  const scope = tab && tab.url ? new URL(tab.url).origin : 'popup';
  const mapping = await bg({ type: 'getMapping', scope });
  const { text, n } = restoreWith($('restorein').value, mapping);
  if (!n) {
    $('restoremsg').textContent = Object.keys(mapping).length
      ? 'Nessun placeholder riconosciuto in questo testo.'
      : 'Nessuna mappa per questa scheda: apri il popup dalla scheda della chat in cui hai inviato il messaggio.';
    return;
  }
  $('restorein').value = text;
  await navigator.clipboard.writeText(text);
  $('restoremsg').textContent = `${n} valori ripristinati e copiati negli appunti.`;
});

$('clear').addEventListener('click', async () => {
  await bg({ type: 'clearMappings' });
  $('clear').textContent = 'Mappe dimenticate';
});

loadSettings();
checkHealth();
