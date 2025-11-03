(() => {
  function connectSSE(url) {
    if (!window.EventSource) return;
    const es = new EventSource(url);
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data || '{}');
        if (data.type === 'stock' || data.type === 'price' || data.type === 'material_created' || data.type === 'material_deleted' || data.type === 'alert') {
          // Simple strategy: reload to keep code small and reliable
          // In a real app, update the specific row.
          if (location.pathname === '/' || location.pathname.startsWith('/materials')) {
            window.location.reload();
          }
        }
      } catch (e) {
        // ignore
      }
    };
    es.onerror = () => {
      // Try reconnect later
      setTimeout(() => {
        es.close();
        connectSSE(url);
      }, 5000);
    };
  }

  if (window.IOT_SSE_URL) {
    connectSSE(window.IOT_SSE_URL);
  }
})();


