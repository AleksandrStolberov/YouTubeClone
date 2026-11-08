import { bindAuth } from "./js/auth.js";
import { bindChannel } from "./js/channel.js";
import { bindFeed } from "./js/feed.js";
import { bindModeration } from "./js/moderation.js";
import { bindRouter } from "./js/router.js";
import { bindSearch } from "./js/search.js";
import { bindUpload } from "./js/upload.js";
import { bindWatch } from "./js/watch.js";

const feed = bindFeed();
bindAuth();
bindRouter({
  feed,
  watch: bindWatch(),
  channel: bindChannel(),
  moderation: bindModeration(),
  search: bindSearch(),
  upload: bindUpload(),
});

const menuButton = document.querySelector("#menu-button");
menuButton.addEventListener("click", () => {
  const open = document.body.classList.toggle("sidebar-open");
  menuButton.setAttribute("aria-expanded", open ? "true" : "false");
});

document.querySelector("#sidebar").addEventListener("click", (event) => {
  if (!event.target.closest("a")) {
    return;
  }
  document.body.classList.remove("sidebar-open");
  menuButton.setAttribute("aria-expanded", "false");
});
