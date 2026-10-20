// Guardia di rete: gira nel contesto della pagina (world MAIN) e ispeziona ogni
// richiesta in uscita (fetch, XHR, WebSocket, sendBeacon). Se contiene un valore che
// l'utente ha scelto di anonimizzare, lo sostituisce con il suo placeholder prima
// che lasci il browser.
//
// Serve perché sostituire il testo nell'editor non basta: alcune app (Perplexity)
// inviano una copia del testo presa dal proprio stato interno, che può essere
// ancora quella precedente alla sostituzione. Copre anche gli script del sito che
// leggono i valori reali ripristinati nel DOM.
//
// Il prezzo: i valori protetti devono essere visibili in questo contesto, quindi
// anche agli script del sito. Gli stessi valori, però, sono già nel DOM ripristinato.

(() => {
  if (window.__shadowsGuard) return;
  window.__shadowsGuard = true;

  let entries = []; // [{ value, placeholder, regex }]
  let pausedUntil = 0;
  const MIN_TRIGGER = 4; // valori più corti non bastano a far scattare la guardia

  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  function compile(mapping) {
    entries = Object.entries(mapping)
      .filter(([, v]) => typeof v === 'string' && v.trim())
      .sort((a, b) => b[1].length - a[1].length)
      .map(([placeholder, value]) => ({
        value,
        placeholder,
        // Confini di parola: "12" non deve colpire "2012".
        regex: new RegExp(`(?<![\\p{L}\\p{N}])${escapeRe(value).replace(/\s+/g, '\\s+')}(?![\\p{L}\\p{N}])`, 'gu'),
      }));
  }

  document.addEventListener('shadows:mapping', (e) => {
    try { compile(JSON.parse(e.detail)); } catch { /* evento non valido */ }
  });
  document.addEventListener('shadows:pause', (e) => {
    pausedUntil = Date.now() + (Number(e.detail) || 0);
  });
  let restoreMode = 'safe';
  document.addEventListener('shadows:restore', (e) => { restoreMode = String(e.detail); });

  // Il pulsante "copia" delle chat scrive negli appunti dal proprio stato, cioè
  // con i placeholder: qui li si sostituisce con i valori reali. Gli appunti non
  // sono leggibili dalla pagina senza un permesso esplicito dell'utente.
  const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  function restorePlaceholders(text, html = false) {
    let out = text;
    for (const e of entries) {
      const value = html ? escapeHtml(e.value) : e.value;
      const bare = e.placeholder.slice(1, -1);
      out = out.split(e.placeholder).join(value).replace(new RegExp(`\\b${escapeRe(bare)}\\b`, 'g'), value);
    }
    return out;
  }
  const restoring = () => restoreMode !== 'off' && entries.length;

  if (navigator.clipboard && navigator.clipboard.writeText) {
    const origWriteText = navigator.clipboard.writeText.bind(navigator.clipboard);
    navigator.clipboard.writeText = (text) =>
      origWriteText(restoring() && typeof text === 'string' ? restorePlaceholders(text) : text);
  }

  // Perplexity copia con clipboard.write e un ClipboardItem (testo e HTML).
  if (navigator.clipboard && navigator.clipboard.write && window.ClipboardItem) {
    const origWrite = navigator.clipboard.write.bind(navigator.clipboard);
    navigator.clipboard.write = async (items) => {
      if (!restoring()) return origWrite(items);
      try {
        const rebuilt = await Promise.all([...items].map(async (item) => {
          const parts = {};
          for (const type of item.types) {
            const blob = await item.getType(type);
            parts[type] = type === 'text/plain' || type === 'text/html'
              ? new Blob([restorePlaceholders(await blob.text(), type === 'text/html')], { type })
              : blob;
          }
          return new ClipboardItem(parts);
        }));
        return origWrite(rebuilt);
      } catch {
        return origWrite(items);
      }
    };
  }

  const active = () => entries.length && Date.now() > pausedUntil;

  function triggers(text) {
    return entries.some((e) => e.value.length >= MIN_TRIGGER && (e.regex.lastIndex = 0, e.regex.test(text)));
  }

  function scrubString(s) {
    let out = s;
    for (const e of entries) out = out.replace(e.regex, e.placeholder);
    return out;
  }

  function scrubJson(node) {
    if (typeof node === 'string') return scrubString(node);
    if (Array.isArray(node)) return node.map(scrubJson);
    if (node && typeof node === 'object') {
      const out = {};
      for (const [k, v] of Object.entries(node)) out[k] = scrubJson(v);
      return out;
    }
    return node; // numeri e booleani restano intatti
  }

  function jsonStrings(node, out = []) {
    if (typeof node === 'string') out.push(node);
    else if (node && typeof node === 'object') Object.values(node).forEach((v) => jsonStrings(v, out));
    return out;
  }

  // Ritorna il corpo ripulito, oppure null se non c'era nulla da fare.
  // Scatta solo se compare almeno un valore protetto "lungo": così i valori brevi
  // (un numero civico) non riscrivono richieste che non c'entrano nulla.
  function scrubBody(text) {
    if (!active() || typeof text !== 'string' || !text) return null;
    let cleaned;
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
    if (parsed !== undefined && typeof parsed === 'object' && parsed !== null) {
      // JSON: si guardano e si modificano solo i valori stringa, già decodificati.
      if (!triggers(jsonStrings(parsed).join('\n'))) return null;
      cleaned = JSON.stringify(scrubJson(parsed));
    } else {
      if (!triggers(text)) return null;
      cleaned = scrubString(text);
    }
    if (cleaned === text) return null;
    document.dispatchEvent(new CustomEvent('shadows:scrubbed'));
    return cleaned;
  }

  // fetch
  const origFetch = window.fetch;
  window.fetch = async function (input, init) {
    try {
      if (active()) {
        if (init && typeof init.body === 'string') {
          const cleaned = scrubBody(init.body);
          if (cleaned !== null) init = { ...init, body: cleaned };
        } else if (init && init.body instanceof URLSearchParams) {
          const cleaned = scrubBody(init.body.toString());
          if (cleaned !== null) init = { ...init, body: new URLSearchParams(cleaned) };
        } else if (input instanceof Request && !(init && 'body' in init) && !['GET', 'HEAD'].includes(input.method)) {
          const cleaned = scrubBody(await input.clone().text());
          if (cleaned !== null) input = new Request(input, { body: cleaned });
        }
      }
    } catch { /* in caso di errore la richiesta prosegue com'era */ }
    return origFetch.call(this, input, init);
  };

  // XMLHttpRequest
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (body) {
    const cleaned = typeof body === 'string' ? scrubBody(body) : null;
    return origSend.call(this, cleaned !== null ? cleaned : body);
  };

  // WebSocket
  const origWsSend = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) {
    const cleaned = typeof data === 'string' ? scrubBody(data) : null;
    return origWsSend.call(this, cleaned !== null ? cleaned : data);
  };

  // sendBeacon (telemetria)
  if (navigator.sendBeacon) {
    const origBeacon = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = (url, data) => {
      const cleaned = typeof data === 'string' ? scrubBody(data) : null;
      return origBeacon(url, cleaned !== null ? cleaned : data);
    };
  }
})();
