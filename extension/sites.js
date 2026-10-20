// Selettori per i siti di chat. Le interfacce cambiano spesso: se Shadows smette di
// intercettare l'invio su un sito, di solito basta aggiornare il pulsante qui.

// Qualunque campo di testo conta come composer, anche la casella di modifica di un
// messaggio già inviato: altrimenti modificarlo aggirerebbe il controllo.
const SHADOWS_COMPOSER = 'textarea, [contenteditable="true"], [contenteditable=""], [contenteditable="plaintext-only"]';

const SHADOWS_GENERIC_SEND = [
  'button[type="submit"]',
  'button[data-testid*="send" i]',
  'button[aria-label*="send" i]',
  'button[aria-label*="invia" i]',
  'button[aria-label*="submit" i]',
];

const SHADOWS_SITE_SEND = {
  'chatgpt.com': ['#composer-submit-button', 'button[data-testid="send-button"]'],
  'chat.openai.com': ['button[data-testid="send-button"]'],
  'claude.ai': ['button[aria-label="Send message"]', 'button[aria-label="Send Message"]'],
  'www.perplexity.ai': ['button[aria-label="Submit"]'],
  'gemini.google.com': ['button.send-button'],
  '127.0.0.1:8765': ['#send'],
  'localhost:8765': ['#send'],
};

function shadowsSiteConfig(host) {
  return {
    composer: SHADOWS_COMPOSER,
    send: [...(SHADOWS_SITE_SEND[host] || []), ...SHADOWS_GENERIC_SEND].join(', '),
  };
}
