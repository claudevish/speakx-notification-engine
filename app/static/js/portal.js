/* Portal shared utilities */

const Portal = {
  /** Make a GET request to a portal API endpoint */
  async get(path) {
    const res = await fetch(`/portal/api${path}`);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  },

  /** Make a POST request with JSON body */
  async post(path, body) {
    const res = await fetch(`/portal/api${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  },

  /** Make a POST request with FormData (file upload) */
  async upload(path, formData) {
    const res = await fetch(`/portal/api${path}`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  },

  /** Make a PUT request with JSON body */
  async put(path, body) {
    const res = await fetch(`/portal/api${path}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  },

  /** Format a number with commas (Indian style) */
  formatNumber(n) {
    if (n === null || n === undefined) return '0';
    return n.toLocaleString('en-IN');
  },

  /** Format a date string to readable format */
  formatDate(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-IN', {
      day: 'numeric', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  },

  /** Truncate text to max length */
  truncate(text, max = 60) {
    if (!text || text.length <= max) return text || '';
    return text.slice(0, max) + '...';
  },
};
