function parseHash() {
  const raw = (location.hash || "#/").replace(/^#/, "");
  const splitAt = raw.indexOf("?");
  const path = splitAt === -1 ? raw : raw.slice(0, splitAt);
  const params = new URLSearchParams(splitAt === -1 ? "" : raw.slice(splitAt + 1));
  return { path: path || "/", params };
}

export function bindRouter(screens) {
  const panels = {
    home: document.querySelector("#home"),
    watch: document.querySelector("#watch"),
    channel: document.querySelector("#channel"),
    moderation: document.querySelector("#moderation"),
    search: document.querySelector("#search"),
  };

  function show(name) {
    for (const [key, node] of Object.entries(panels)) {
      node.hidden = key !== name;
    }
    document.body.dataset.route = name;
  }

  function apply() {
    const { path, params } = parseHash();
    const watchMatch = path.match(/^\/watch\/([0-9a-f-]{36})$/i);
    const channelMatch = path.match(/^\/channel\/([0-9a-f-]{36})$/i);
    if (path !== "/upload") {
      screens.upload.close();
    }
    if (watchMatch) {
      show("watch");
      screens.watch.open(watchMatch[1]);
      return;
    }
    screens.watch.close();
    if (channelMatch) {
      show("channel");
      screens.channel.open(channelMatch[1]);
      return;
    }
    if (path === "/moderation") {
      show("moderation");
      screens.moderation.open();
      return;
    }
    if (path === "/search") {
      show("search");
      screens.search.open(params.get("q") || "");
      return;
    }
    show("home");
    screens.feed.reload();
    if (path === "/upload") {
      screens.upload.open();
    }
  }

  window.addEventListener("hashchange", apply);
  apply();
}
