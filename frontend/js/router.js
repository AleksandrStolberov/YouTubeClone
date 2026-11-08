const WATCH_ROUTE = /^#\/watch\/([0-9a-f-]{36})$/i;

export function bindRouter(watch) {
  function apply() {
    const match = location.hash.match(WATCH_ROUTE);
    if (match) {
      watch.open(match[1]);
      return;
    }
    watch.showHome();
  }

  window.addEventListener("hashchange", apply);
  apply();
}
