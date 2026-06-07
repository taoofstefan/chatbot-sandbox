// HTMX auto-redirects / etc. could go here. Currently a placeholder.
document.body.addEventListener("htmx:afterRequest", (e) => {
  if (e.detail.xhr.status === 400) {
    console.error("htmx error", e.detail);
  }
});
