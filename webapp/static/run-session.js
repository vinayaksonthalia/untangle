/* Results are tab-local display data, never trusted certificate evidence. */
(() => {
  'use strict';
  const key = 'untangle_results';
  const urls = [];
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  function clear() { try { sessionStorage.removeItem(key); } catch (_) {} }
  function read() {
    try {
      const raw = sessionStorage.getItem(key);
      if (!raw) return null;
      if (raw.length > 4 * 1024 * 1024) throw new Error('Result too large');
      const b = JSON.parse(raw);
      if (!object(b) || b.version !== 1 || !['demo', 'your_run'].includes(b.mode) ||
          !object(b.presentation) || !object(b.investigations) ||
          !Array.isArray(b.investigations.cases) || !object(b.certificate) ||
          typeof b.journal_tally_xml !== 'string') throw new Error('Invalid result');
      return b;
    } catch (_) { clear(); return null; }
  }
  window.untangleTabBundle = read;
  window.untangleFetch = async path => {
    const fields = {'/api/presentation/current': 'presentation',
      '/api/investigations/current': 'investigations', '/api/certificate/current': 'certificate'};
    if (!Object.prototype.hasOwnProperty.call(fields, path)) throw new Error('Unsupported result path');
    const b = read();
    return new Response(JSON.stringify(b ? b[fields[path]] : {mode: 'empty'}), {
      status: !b && fields[path] === 'certificate' ? 404 : 200,
      headers: {'Content-Type': 'application/json'}});
  };
  document.addEventListener('DOMContentLoaded', () => {
    const b = read();
    function download(selector, value, type, filename) {
      document.querySelectorAll(selector).forEach(a => {
        a.removeAttribute('href');
        if (!b) { a.setAttribute('aria-disabled', 'true'); return; }
        const url = URL.createObjectURL(new Blob([value], {type}));
        urls.push(url); a.href = url; a.download = filename;
      });
    }
    download('a[href="/api/journal/current.tally.xml"]', b && b.journal_tally_xml, 'application/xml', 'untangle-journal.xml');
    if (b) {
      const notice = document.createElement('aside');
      notice.style.cssText = 'padding:12px 24px;font-size:12px;border-top:1px solid #ddd';
      notice.appendChild(document.createTextNode('Results saved in this tab. Browser session restore may retain them. '));
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = 'Clear this tab’s results';
      button.style.textDecoration = 'underline';
      button.addEventListener('click', () => {
        try {
          sessionStorage.removeItem(key);
          location.replace('/dashboard');
        } catch (_) { button.textContent = 'Storage unavailable—clear this site’s data in browser settings'; }
      });
      notice.appendChild(button); (document.querySelector('main') || document.body).appendChild(notice);
    }
  });
  window.addEventListener('pagehide', () => urls.forEach(url => URL.revokeObjectURL(url)));
  // Back/forward cache can otherwise revive old rendered results after clearing.
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
})();
