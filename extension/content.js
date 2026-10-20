// Content script: intercetta l'invio del messaggio prima che lasci il browser,
// lo fa analizzare al servizio locale e, se serve, sostituisce il testo con la
// versione anonimizzata.
//
// Valori reali nelle risposte, tre modalità (impostazione "restore"):
//   safe  la pagina resta con i placeholder; il valore reale compare passando il
//         mouse (riquadro in shadow DOM chiuso) e quando si copia. Gli script del
//         sito (telemetria, registrazione di sessione) non lo vedono mai.
//   dom   i placeholder vengono sostituiti nel testo della pagina: comodo, ma ogni
//         script del sito può leggerli e spedirli.
//   off   nessun ripristino.

(() => {
  const site = shadowsSiteConfig(location.host);
  const scope = location.origin;
  const settings = { enabled: true, restore: 'safe', failMode: 'ask', blockFiles: false };
  const restoreMode = (v) => (v === true ? 'safe' : v === false ? 'off' : v || 'safe');
  let mapping = {};
  let bypass = false;
  let busy = false;

  // --- Comunicazione con il service worker -----------------------------------

  function send(msg) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(msg, (resp) => {
        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
        if (!resp) return reject(new Error('nessuna risposta dal service worker'));
        resp.ok ? resolve(resp.data) : reject(new Error(resp.error));
      });
    });
  }

  function logOutcome(proposed, taken) {
    send({ type: 'event', event: { site: location.host, proposed, taken } }).catch(() => {});
  }

  // La guardia di rete (guard.js, nel contesto della pagina) riceve i valori da
  // proteggere: se l'app invia una copia vecchia del testo, li sostituisce lei.
  function armGuard() {
    document.dispatchEvent(new CustomEvent('shadows:mapping', { detail: JSON.stringify(mapping) }));
    document.dispatchEvent(new CustomEvent('shadows:restore', { detail: restoreMode(settings.restore) }));
  }

  // Gli interventi della guardia possono essere decine al secondo (telemetria):
  // nel registro finisce un riepilogo ogni 5 secondi.
  let scrubbed = 0;
  document.addEventListener('shadows:scrubbed', () => {
    if (scrubbed++ === 0) {
      setTimeout(() => { logOutcome('network_guard', `scrubbed_in_flight x${scrubbed}`); scrubbed = 0; }, 5000);
    }
  });

  function remember(newMapping) {
    mapping = { ...mapping, ...newMapping };
    armGuard(); // sincrono: deve essere attivo prima del click su "Invia"
    send({ type: 'saveMapping', scope, mapping: newMapping }).catch(() => {});
    scheduleRestore();
  }

  chrome.storage.local.get(Object.keys(settings)).then((stored) => {
    for (const [k, v] of Object.entries(stored)) if (v !== undefined) settings[k] = v;
    armGuard();
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    for (const [k, { newValue }] of Object.entries(changes)) if (k in settings) settings[k] = newValue;
    armGuard();
    scheduleRestore();
  });
  send({ type: 'getMapping', scope }).then((m) => { mapping = m || {}; armGuard(); scheduleRestore(); }).catch(() => {});

  // --- Composer ----------------------------------------------------------------

  function composerOf(el) {
    if (!el || !el.closest || el.closest('#shadows-host')) return null;
    return el.closest(site.composer);
  }

  function getText(el) {
    return el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' ? el.value : el.innerText;
  }

  const tick = (ms = 40) => new Promise((r) => setTimeout(r, ms));
  const squash = (s) => s.replace(/\s+/g, ' ').trim();

  async function selectAllIn(el) {
    el.focus();
    const range = document.createRange();
    range.selectNodeContents(el);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    // Lexical (Perplexity) e ProseMirror leggono la selezione su 'selectionchange',
    // che è asincrono: senza attesa l'editor crede che il cursore sia ancora in fondo.
    await tick();
  }

  async function setText(el, text) {
    el.focus();
    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, text); // passa da React
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }
    // Editor rich text: si passa dai loro comandi, così aggiornano lo stato interno
    // e non solo il DOM. Primo tentativo insertText, poi un "incolla" simulato.
    await selectAllIn(el);
    document.execCommand('insertText', false, text);
    await tick();
    if (squash(getText(el)) === squash(text)) return;

    await selectAllIn(el);
    const data = new DataTransfer();
    data.setData('text/plain', text);
    el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }));
    await tick(80);
  }

  function findSendButton() {
    return [...document.querySelectorAll(site.send)].find((b) => !b.closest('#shadows-host')) || null;
  }

  function submit(composer, via, button) {
    bypass = true;
    setTimeout(() => { bypass = false; }, 1000);
    // Un attimo di respiro: React e gli editor aggiornano il loro stato in modo
    // asincrono. La guardia di rete copre comunque il caso in cui non basti.
    setTimeout(() => {
      if (via === 'form' && button) return button.requestSubmit();
      const btn = button && button.isConnected && !button.disabled ? button : findSendButton();
      if (btn && !btn.disabled) return btn.click();
      composer.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true,
      }));
    }, 250);
  }

  // --- Intercettazione ---------------------------------------------------------

  window.addEventListener('keydown', (e) => {
    if (bypass || !settings.enabled) return;
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
    const composer = composerOf(e.target);
    if (!composer) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    intercept(composer, 'enter');
  }, true);

  window.addEventListener('click', (e) => {
    if (bypass || !settings.enabled) return;
    const btn = e.target.closest && e.target.closest(site.send);
    if (!btn || btn.closest('#shadows-host')) return;
    const composer = composerOf(document.activeElement) || composerOf(btn.form && btn.form.querySelector(site.composer))
      || nearestComposer(btn);
    if (!composer) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    intercept(composer, 'click', btn);
  }, true);

  window.addEventListener('submit', (e) => {
    if (bypass || !settings.enabled) return;
    const composer = e.target.querySelector && e.target.querySelector(site.composer);
    if (!composer) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    intercept(composer, 'form', e.target);
  }, true);

  function nearestComposer(btn) {
    // Risale dal pulsante fino al primo antenato che contiene un composer.
    for (let node = btn.parentElement; node && node !== document.body; node = node.parentElement) {
      const found = node.querySelector(site.composer);
      if (found) return found;
    }
    return null;
  }

  async function intercept(composer, via, button) {
    if (busy) return;
    const text = getText(composer);
    if (!text.trim()) return submit(composer, via, button);
    busy = true;
    try {
      let res;
      try {
        res = await send({ type: 'analyze', text, site: location.host, known: mapping });
      } catch (err) {
        return await serviceDown(composer, via, button, err);
      }
      if (res.action === 'allow') {
        logOutcome('allow', 'sent_original');
        return submit(composer, via, button);
      }
      const choice = await showDialog(res, text);
      if (choice.kind === 'cancel') return logOutcome(res.action, 'cancelled');
      if (choice.kind === 'original') {
        // Scelta esplicita dell'utente: la guardia non deve riscrivere questo invio.
        document.dispatchEvent(new CustomEvent('shadows:pause', { detail: '4000' }));
        logOutcome(res.action, 'sent_original');
        return submit(composer, via, button);
      }
      await setText(composer, choice.text);
      // Rete di sicurezza: se l'editor non ha accettato il nuovo testo, NON si invia.
      const now = getText(composer);
      const leaked = Object.values(choice.mapping).filter((v) => now.includes(v) && !choice.text.includes(v));
      if (leaked.length) {
        toast('Shadows non è riuscito a sostituire il testo in questo editor: invio annullato. ' +
              'Copia il testo anonimizzato dall\'anteprima e incollalo a mano.', 'error');
        return logOutcome(res.action, 'replace_failed');
      }
      remember(choice.mapping);
      logOutcome(res.action, choice.partial ? 'sent_partial' : 'sent_anonymized');
      submit(composer, via, button);
    } finally {
      busy = false;
    }
  }

  async function serviceDown(composer, via, button, err) {
    // Estensione ricaricata con la scheda già aperta: questo script è scollegato e
    // non può più controllare nulla. Non è un guasto del servizio: si ricarica la pagina.
    if (/context invalidated/i.test(String(err && err.message))) {
      await showDialog({
        action: 'block', serviceError: 'stale', entities: [], reasons: [], detectors: {}, score: 0,
      }, getText(composer));
      return;
    }
    if (settings.failMode === 'open') {
      toast('Servizio Shadows non raggiungibile: messaggio inviato senza controllo.', 'warn');
      return submit(composer, via, button);
    }
    const choice = await showDialog({
      action: settings.failMode === 'closed' ? 'block' : 'warn',
      serviceError: String(err.message || err),
      entities: [], reasons: [], detectors: {}, score: 0,
    }, getText(composer));
    if (choice.kind === 'original') {
      logOutcome('service_down', 'sent_unchecked');
      submit(composer, via, button);
    }
  }

  // --- Ricostruzione del testo con offset Python -----------------------------
  // Il servizio conta i caratteri in code point (Python), JavaScript in unità
  // UTF-16: con un'emoji nel testo gli offset non coinciderebbero.

  function buildAnonymized(text, entities, selected) {
    const cps = Array.from(text);
    let out = '';
    let cursor = 0;
    const used = {};
    entities.forEach((e, i) => {
      if (!selected.has(i)) return;
      out += cps.slice(cursor, e.start).join('') + e.placeholder;
      cursor = e.end;
      used[e.placeholder] = e.value;
    });
    return { text: out + cps.slice(cursor).join(''), mapping: used };
  }

  // --- Dialogo -----------------------------------------------------------------

  const TITLES = {
    warn: 'Dati potenzialmente sensibili',
    redact: 'Dati sensibili: il messaggio partirà anonimizzato',
    block: 'Invio bloccato',
  };

  function showDialog(res, originalText) {
    return new Promise((resolve) => {
      const host = document.createElement('div');
      host.id = 'shadows-host';
      const root = host.attachShadow({ mode: 'closed' });
      root.innerHTML = DIALOG_CSS + `
        <div class="backdrop">
          <div class="dialog ${res.action}" role="dialog" aria-modal="true" aria-labelledby="t">
            <h2 id="t"></h2>
            <p class="sub"></p>
            <ul class="list"></ul>
            <label class="pv-label">Anteprima di ciò che riceverà l'AI</label>
            <textarea class="preview" readonly></textarea>
            <p class="note"></p>
            <div class="buttons"></div>
          </div>
        </div>`;
      const $ = (s) => root.querySelector(s);
      const entities = res.entities || [];
      const selected = new Set(entities.map((_, i) => i));

      const stale = res.serviceError === 'stale';
      $('h2').textContent = stale ? 'Shadows è stato aggiornato: ricarica la pagina'
        : res.serviceError ? 'Servizio Shadows non raggiungibile' : TITLES[res.action];
      $('.sub').textContent = stale
        ? 'Questa scheda era aperta prima dell\'aggiornamento dell\'estensione e non può più controllare i messaggi. Premi F5, poi invia di nuovo: il testo va ricopiato.'
        : res.serviceError
          ? `Il messaggio non può essere controllato (${res.serviceError}). Se Shadows non è registrato presso il browser: "python -m shadows install-native".`
          : (res.reasons || []).join(' · ');

      const notes = [];
      if (res.detectors && res.detectors['rizzo-pii'] === 'non raggiungibile') {
        notes.push('NER rizzo-pii non raggiungibile: nomi di persona e indirizzi potrebbero sfuggire.');
      } else if (res.detectors && res.detectors['rizzo-pii'] === 'disattivato') {
        notes.push('Senza NER (rizzo-pii disattivato) i nomi di persona non vengono riconosciuti.');
      }
      if (res.action === 'block' && !res.serviceError) {
        notes.push('Il contenuto include elementi che la policy non consente di inviare nemmeno anonimizzati (es. credenziali: vanno ruotate).');
      }
      $('.note').textContent = notes.join(' ');

      const list = $('.list');
      entities.forEach((e, i) => {
        const li = document.createElement('li');
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.checked = true;
        box.disabled = !e.optional || res.action === 'block';
        box.title = e.optional ? 'Deseleziona per lasciare il valore in chiaro' : 'Imposto dalla policy';
        box.addEventListener('change', () => {
          box.checked ? selected.add(i) : selected.delete(i);
          refresh();
        });
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.textContent = e.label;
        const value = document.createElement('span');
        value.className = 'value';
        value.textContent = e.value;
        const ph = document.createElement('span');
        ph.className = 'ph';
        ph.textContent = `→ ${e.placeholder}`;
        li.append(box, badge, value, ph);
        list.append(li);
      });
      if (!entities.length) list.remove();

      const preview = $('.preview');
      function refresh() {
        preview.value = res.serviceError ? originalText : buildAnonymized(originalText, entities, selected).text;
      }
      refresh();

      function close(result) {
        document.removeEventListener('keydown', onKey, true);
        host.remove();
        resolve(result);
      }
      function onKey(ev) {
        if (ev.key === 'Escape') { ev.stopImmediatePropagation(); close({ kind: 'cancel' }); }
      }
      document.addEventListener('keydown', onKey, true);

      const buttons = $('.buttons');
      function addButton(label, cls, result) {
        const b = document.createElement('button');
        b.textContent = label;
        b.className = cls;
        b.addEventListener('click', () => close(result()));
        buttons.append(b);
        return b;
      }
      addButton('Annulla', 'secondary', () => ({ kind: 'cancel' }));
      if (res.serviceError && res.action === 'warn') {
        addButton('Invia senza controllo', 'danger', () => ({ kind: 'original' }));
      } else if (!res.serviceError) {
        if (res.action === 'warn') addButton('Invia originale', 'secondary', () => ({ kind: 'original' }));
        if (res.action === 'warn' || res.action === 'redact') {
          addButton('Invia anonimizzato', 'primary', () => {
            const built = buildAnonymized(originalText, entities, selected);
            return { kind: 'anonymized', text: built.text, mapping: built.mapping,
                     partial: selected.size < entities.length };
          });
        }
      }
      document.documentElement.append(host);
      // Il focus si può dare solo dopo l'inserimento nel DOM. Invio conferma la scelta
      // sicura: "Invia anonimizzato" se c'è, altrimenti "Annulla", mai un invio in chiaro.
      (buttons.querySelector('.primary') || buttons.firstElementChild).focus();
    });
  }

  function toast(message, kind = 'info') {
    const host = document.createElement('div');
    const root = host.attachShadow({ mode: 'closed' });
    root.innerHTML = DIALOG_CSS + `<div class="toast ${kind}"></div>`;
    root.querySelector('.toast').textContent = message;
    document.documentElement.append(host);
    setTimeout(() => host.remove(), 6000);
  }

  // --- Allegati ------------------------------------------------------------------
  // I file allegati direttamente alla chat non passano dal composer: li segnaliamo
  // (o li blocchiamo, se configurato) e rimandiamo al caricamento dal popup.

  function onFiles(e, files) {
    if (!settings.enabled || !files || !files.length) return;
    if (settings.blockFiles) {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (e.target && e.target.type === 'file') e.target.value = '';
      toast('Allegato bloccato da Shadows: carica il documento dal popup di Shadows per anonimizzarlo.', 'error');
    } else {
      toast('Gli allegati NON vengono analizzati da Shadows: per i documenti riservati usa il popup di Shadows.', 'warn');
    }
  }
  window.addEventListener('change', (e) => { if (e.target && e.target.type === 'file') onFiles(e, e.target.files); }, true);
  window.addEventListener('drop', (e) => onFiles(e, e.dataTransfer && e.dataTransfer.files), true);
  window.addEventListener('paste', (e) => onFiles(e, e.clipboardData && e.clipboardData.files), true);

  // --- Documento anonimizzato dal popup -------------------------------------------

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type !== 'insertDocument') return;
    const composer = document.querySelector(site.composer);
    if (!composer) { sendResponse({ ok: false, error: 'campo di testo della chat non trovato' }); return; }
    const current = getText(composer).trim();
    setText(composer, current ? `${current}\n\n${msg.text}` : msg.text).then(() => {
      remember(msg.mapping || {});
      sendResponse({ ok: true });
    });
    return true; // risposta asincrona
  });

  // --- Ripristino dei valori nelle risposte ---------------------------------------
  // Modalità "dom": si modifica il testo dei nodi già renderizzati. I valori reali
  // non tornano nello stato dell'applicazione, ma gli script della pagina li vedono.

  let restoreTimer = null;
  let restoreRegex = null;
  let restoreKey = '';

  function scheduleRestore() {
    // Throttle, non debounce: durante lo streaming della risposta il DOM cambia di
    // continuo e un debounce rimanderebbe il ripristino fino alla fine.
    if (restoreTimer) return;
    restoreTimer = setTimeout(() => { restoreTimer = null; restoreDom(); }, 200);
  }

  function buildRegex() {
    const names = Object.keys(mapping).map((ph) => ph.replace(/^\[|\]$/g, ''));
    const key = names.join('|');
    if (key === restoreKey) return restoreRegex;
    restoreKey = key;
    if (!names.length) return (restoreRegex = null);
    const alt = names.sort((a, b) => b.length - a.length).map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
    return (restoreRegex = new RegExp(`\\[(${alt})\\]|\\b(${alt})\\b`, 'g'));
  }

  function restoreText(text) {
    const regex = buildRegex();
    return regex ? text.replace(regex, (m, a, b) => mapping[`[${a || b}]`] ?? m) : text;
  }

  // --- Modalità "safe": valore reale al passaggio del mouse e nella copia ----------
  // Il riquadro vive in uno shadow DOM chiuso: gli script della pagina, inclusa la
  // registrazione di sessione, non possono leggerne il contenuto.

  let tipHost = null;
  let tipBox = null;
  function tip() {
    if (tipHost && tipHost.isConnected) return tipBox;
    tipHost = document.createElement('div');
    tipHost.id = 'shadows-tip';
    const root = tipHost.attachShadow({ mode: 'closed' });
    root.innerHTML = `<style>
      .tip { position: fixed; z-index: 2147483647; pointer-events: none; display: none;
        max-width: 360px; padding: 6px 9px; border-radius: 8px; background: #1e3a8a; color: #fff;
        font: 13px/1.4 system-ui, "Segoe UI", sans-serif; box-shadow: 0 6px 20px rgba(0,0,0,.3); }
      .tip small { display: block; opacity: .75; font-size: 11px; }
    </style><div class="tip"></div>`;
    tipBox = root.querySelector('.tip');
    document.documentElement.append(tipHost);
    return tipBox;
  }

  function placeholderAt(x, y) {
    const range = document.caretRangeFromPoint && document.caretRangeFromPoint(x, y);
    const node = range && range.startContainer;
    if (!node || node.nodeType !== Node.TEXT_NODE) return null;
    const regex = buildRegex();
    if (!regex) return null;
    regex.lastIndex = 0;
    for (let m; (m = regex.exec(node.nodeValue));) {
      if (range.startOffset >= m.index && range.startOffset <= m.index + m[0].length) {
        const ph = `[${m[1] || m[2]}]`;
        return mapping[ph] !== undefined ? { ph, value: mapping[ph] } : null;
      }
    }
    return null;
  }

  let lastMove = 0;
  window.addEventListener('mousemove', (e) => {
    if (restoreMode(settings.restore) !== 'safe' || !Object.keys(mapping).length) return;
    const now = Date.now();
    if (now - lastMove < 60) return;
    lastMove = now;
    const hit = placeholderAt(e.clientX, e.clientY);
    const box = tip();
    if (!hit) { box.style.display = 'none'; return; }
    box.replaceChildren(document.createTextNode(hit.value));
    const small = document.createElement('small');
    small.textContent = `l'AI ha ricevuto ${hit.ph} · copiando ottieni il valore reale`;
    box.append(small);
    box.style.left = `${Math.min(e.clientX + 12, window.innerWidth - 370)}px`;
    box.style.top = `${e.clientY + 16}px`;
    box.style.display = 'block';
  }, { passive: true });

  // Copia con Ctrl+C o menu: negli appunti vanno i valori reali.
  window.addEventListener('copy', (e) => {
    if (restoreMode(settings.restore) === 'off' || !Object.keys(mapping).length) return;
    const sel = window.getSelection();
    const text = sel ? sel.toString() : '';
    const restored = restoreText(text);
    if (!text || restored === text || composerOf(sel.anchorNode && sel.anchorNode.parentElement)) return;
    e.clipboardData.setData('text/plain', restored);
    e.preventDefault();
    e.stopImmediatePropagation();
  }, true);

  function restoreDom() {
    if (restoreMode(settings.restore) !== 'dom' || !document.body) return;
    const regex = buildRegex();
    if (!regex) return;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || parent.closest('textarea, [contenteditable="true"], [contenteditable=""], #shadows-host, [data-shadows-ignore], script, style')) {
          return NodeFilter.FILTER_REJECT;
        }
        regex.lastIndex = 0;
        return regex.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      },
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const swapped = [];
      node.nodeValue = node.nodeValue.replace(regex, (m, a, b) => {
        const value = mapping[`[${a || b}]`];
        if (value === undefined) return m;
        swapped.push(`${value} ← [${a || b}]`);
        return value;
      });
      const parent = node.parentElement;
      parent.classList.add('shadows-restored');
      const previous = parent.dataset.shadowsSwapped ? parent.dataset.shadowsSwapped.split('\n') : [];
      const all = [...new Set([...previous, ...swapped])];
      parent.dataset.shadowsSwapped = all.join('\n');
      parent.title = 'Shadows: valori reali mostrati SOLO sul tuo schermo.\n' +
        `L'AI ha ricevuto i placeholder:\n${all.join('\n')}`;
    }
  }

  new MutationObserver(scheduleRestore).observe(document.documentElement, {
    childList: true, subtree: true, characterData: true,
  });

  const DIALOG_CSS = `<style>
    :host { all: initial; }
    .backdrop { position: fixed; inset: 0; z-index: 2147483647; background: rgba(15, 18, 25, .55);
      display: flex; align-items: center; justify-content: center; padding: 16px;
      font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
    .dialog { background: #fff; color: #1b1f27; border-radius: 12px; width: min(640px, 100%);
      max-height: calc(100vh - 32px); overflow: auto; padding: 20px 22px; box-shadow: 0 20px 60px rgba(0,0,0,.35);
      border-top: 5px solid #d97706; }
    .dialog.redact { border-top-color: #2563eb; }
    .dialog.block { border-top-color: #dc2626; }
    h2 { margin: 0 0 4px; font-size: 18px; }
    .sub { margin: 0 0 12px; color: #4b5563; font-size: 13px; }
    .list { list-style: none; margin: 0 0 12px; padding: 0; border: 1px solid #e5e7eb; border-radius: 8px;
      max-height: 220px; overflow: auto; }
    .list li { display: flex; gap: 8px; align-items: center; padding: 6px 10px; border-bottom: 1px solid #f1f2f4; }
    .list li:last-child { border-bottom: 0; }
    .badge { font: 600 11px/1 ui-monospace, Consolas, monospace; background: #eef2ff; color: #3730a3;
      padding: 4px 6px; border-radius: 4px; white-space: nowrap; }
    .value { flex: 1; overflow-wrap: anywhere; }
    .ph { color: #6b7280; font: 12px ui-monospace, Consolas, monospace; white-space: nowrap; }
    .pv-label { display: block; font-size: 12px; color: #4b5563; margin-bottom: 4px; }
    .preview { width: 100%; box-sizing: border-box; min-height: 110px; resize: vertical; border: 1px solid #d1d5db;
      border-radius: 8px; padding: 8px; font: 13px/1.4 ui-monospace, Consolas, monospace; background: #f9fafb; color: inherit; }
    .note { color: #92400e; font-size: 12px; margin: 8px 0 0; }
    .note:empty { display: none; }
    .buttons { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
    button { font: 600 14px system-ui, sans-serif; border-radius: 8px; padding: 8px 14px; cursor: pointer; border: 1px solid #d1d5db; }
    .primary { background: #2563eb; color: #fff; border-color: #2563eb; }
    .secondary { background: #fff; color: #1b1f27; }
    .danger { background: #dc2626; color: #fff; border-color: #dc2626; }
    button:focus-visible, input:focus-visible { outline: 3px solid #93c5fd; outline-offset: 2px; }
    .toast { position: fixed; z-index: 2147483647; right: 16px; bottom: 16px; max-width: min(420px, calc(100vw - 32px));
      padding: 12px 14px; border-radius: 10px; color: #fff; background: #1f2937; box-shadow: 0 10px 30px rgba(0,0,0,.3);
      font: 14px/1.4 system-ui, sans-serif; }
    .toast.warn { background: #b45309; }
    .toast.error { background: #b91c1c; }
    @media (prefers-color-scheme: dark) {
      .dialog { background: #1c1f26; color: #e5e7eb; }
      .sub, .pv-label { color: #9ca3af; }
      .list, .list li { border-color: #2d323c; }
      .badge { background: #312e81; color: #e0e7ff; }
      .preview { background: #111318; border-color: #374151; }
      .secondary { background: #1c1f26; color: #e5e7eb; border-color: #4b5563; }
      .note { color: #fbbf24; }
    }
  </style>`;
})();
