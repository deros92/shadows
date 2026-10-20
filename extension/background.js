// Service worker: unico punto che parla con Shadows.
//
// Trasporto principale: native messaging. È il browser ad avviare Shadows e a
// parlarci attraverso un canale privato: nessuna porta di rete aperta, nessuna
// finestra da tenere accesa. La connessione si apre all'avvio del browser (così il
// modello è già caricato quando serve) e, finché è aperta, tiene vivo il service worker.
//
// Ripiego: se Shadows non è registrato (python -m shadows install-native), si usa il
// servizio HTTP su 127.0.0.1:8765, se avviato a mano (demo, test).

const NATIVE_HOST = 'com.shadows.host';
const DEFAULT_SERVICE = 'http://127.0.0.1:8765';
const TIMEOUT_MS = 90000; // al primo avvio il modello può impiegare decine di secondi

let port = null;
let nativeAvailable = true; // diventa false se il host non è registrato
let nextId = 1;
const pending = new Map(); // id -> { resolve, reject, timer }
const partial = new Map(); // id -> parti di una risposta spezzata (> 1 MB)

function connectNative() {
  if (port || !nativeAvailable) return port;
  try {
    port = chrome.runtime.connectNative(NATIVE_HOST);
  } catch (err) {
    nativeAvailable = false;
    return null;
  }
  port.onMessage.addListener(onNativeMessage);
  port.onDisconnect.addListener(() => {
    const reason = (chrome.runtime.lastError && chrome.runtime.lastError.message) || 'canale chiuso';
    port = null;
    const missing = /not found|forbidden|non trovato/i.test(reason);
    if (missing) nativeAvailable = false;
    for (const [, p] of pending) {
      clearTimeout(p.timer);
      const err = new Error(`Shadows non disponibile: ${reason}`);
      err.hostMissing = missing;
      p.reject(err);
    }
    pending.clear();
    partial.clear();
  });
  return port;
}

function onNativeMessage(msg) {
  if (msg.chunk !== undefined) {
    const parts = partial.get(msg.id) || [];
    parts[msg.chunk] = msg.part;
    partial.set(msg.id, parts);
    if (parts.filter((p) => p !== undefined).length < msg.of) return;
    partial.delete(msg.id);
    msg = JSON.parse(parts.join(''));
  }
  const p = pending.get(msg.id);
  if (!p) return;
  pending.delete(msg.id);
  clearTimeout(p.timer);
  msg.ok ? p.resolve(msg.data) : p.reject(new Error(msg.error || 'errore di Shadows'));
}

function nativeRequest(type, payload) {
  return new Promise((resolve, reject) => {
    const p = connectNative();
    if (!p) {
      const err = new Error('native messaging non disponibile');
      err.hostMissing = true;
      return reject(err);
    }
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error('Shadows non ha risposto in tempo'));
    }, TIMEOUT_MS);
    pending.set(id, { resolve, reject, timer });
    p.postMessage({ id, type, ...payload });
  });
}

// --- Ripiego HTTP ---------------------------------------------------------------

async function httpRequest(type, payload) {
  const { service } = await chrome.storage.local.get('service');
  const base = (service || DEFAULT_SERVICE).replace(/\/$/, '');
  const signal = AbortSignal.timeout(15000);
  const post = (path, body) => fetch(base + path, {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let resp;
  if (type === 'health') resp = await fetch(base + '/health', { signal });
  else if (type === 'analyze') resp = await post('/v1/analyze', payload);
  else if (type === 'event') resp = await post('/v1/event', payload);
  else if (type === 'restore') resp = await post('/v1/restore', payload);
  else if (type === 'document') {
    const bytes = Uint8Array.from(atob(payload.data_b64), (c) => c.charCodeAt(0));
    const form = new FormData();
    form.append('file', new Blob([bytes]), payload.filename);
    form.append('known_mapping', JSON.stringify(payload.known_mapping || {}));
    form.append('site', payload.site || '');
    resp = await fetch(base + '/v1/document', { method: 'POST', body: form, signal });
  } else throw new Error(`richiesta sconosciuta: ${type}`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || `servizio Shadows: HTTP ${resp.status}`);
  if (type === 'health') body.transport = 'http';
  return body;
}

async function request(type, payload = {}) {
  if (nativeAvailable) {
    try {
      return await nativeRequest(type, payload);
    } catch (err) {
      if (!err.hostMissing) throw err;
    }
  }
  return httpRequest(type, payload);
}

// --- Mappa segnaposto -> valore -----------------------------------------------------
// Vive solo in chrome.storage.session: in memoria, cancellata alla chiusura del
// browser, mai scritta su disco né inviata ai siti.
const mapKey = (scope) => `mapping:${scope}`;

async function handle(msg) {
  switch (msg.type) {
    case 'analyze':
      return request('analyze', { text: msg.text, site: msg.site, known_mapping: msg.known || {} });
    case 'document':
      return request('document', {
        filename: msg.filename, data_b64: msg.data_b64, site: msg.site, known_mapping: msg.known || {},
      });
    case 'event':
      return request('event', msg.event);
    case 'health':
      return request('health');
    case 'getMapping': {
      const key = mapKey(msg.scope);
      return (await chrome.storage.session.get(key))[key] || {};
    }
    case 'saveMapping': {
      const key = mapKey(msg.scope);
      const current = (await chrome.storage.session.get(key))[key] || {};
      await chrome.storage.session.set({ [key]: { ...current, ...msg.mapping } });
      return true;
    }
    case 'clearMappings':
      await chrome.storage.session.clear();
      return true;
    default:
      throw new Error(`messaggio sconosciuto: ${msg.type}`);
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  handle(msg).then(
    (data) => sendResponse({ ok: true, data }),
    (err) => sendResponse({ ok: false, error: String(err && err.message ? err.message : err) }),
  );
  return true; // risposta asincrona
});

// Avvio del browser (e del service worker): si apre subito il canale, così Shadows
// carica il modello in anticipo.
chrome.runtime.onStartup.addListener(connectNative);
chrome.runtime.onInstalled.addListener(connectNative);
connectNative();
