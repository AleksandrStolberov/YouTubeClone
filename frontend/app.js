import { bindAuth } from "./js/auth.js";
import { bindFeed } from "./js/feed.js";

bindFeed();
bindAuth();

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
