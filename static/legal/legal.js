// Fills [data-site="field"] values on legal pages (such as the consultation fee) from /api/site-info.
(async () => {
  try {
    const response = await fetch('/api/site-info');
    const info = await response.json();
    document.querySelectorAll('[data-site]').forEach((el) => {
      const value = info[el.dataset.site];
      if (value !== undefined) el.textContent = typeof value === 'number' ? `₹${value.toFixed(2)}` : value;
    });
  } catch (err) {
    // Static placeholders remain visible if the API is unreachable.
  }
})();
