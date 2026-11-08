import { request } from "./api.js";
import { currentUser } from "./auth.js";
import { renderVideoCard } from "./feed.js";
import {
  avatarColor,
  formatResultCount,
  formatSubscribers,
  formatViews,
  plural,
} from "./format.js";

export function bindChannel() {
  const name = document.querySelector("#channel-page-name");
  const avatar = document.querySelector("#channel-page-avatar");
  const stats = document.querySelector("#channel-page-stats");
  const subscribe = document.querySelector("#channel-subscribe");
  const status = document.querySelector("#channel-status");
  const videos = document.querySelector("#channel-videos");
  const playlists = document.querySelector("#channel-playlists");
  const videoTab = document.querySelector("#channel-tab-videos");
  const playlistTab = document.querySelector("#channel-tab-playlists");
  let ticket = 0;
  let activeId = "";
  let profile = null;
  let tab = "videos";

  function paintStats(subscribers) {
    if (!profile) {
      return;
    }
    const count = subscribers ?? profile.subscribers_count;
    stats.textContent = `${formatSubscribers(count)} · ${formatViews(profile.total_views)} · ${formatResultCount(profile.videos_count)}`;
  }

  function paintSubscribe(state) {
    const user = currentUser();
    const own = Boolean(user && profile && user.id === profile.user_id);
    subscribe.hidden = !profile || own;
    if (!state || own) {
      return;
    }
    subscribe.textContent = state.is_subscribed ? "Вы подписаны" : "Подписаться";
    subscribe.classList.toggle("is-subscribed", Boolean(state.is_subscribed));
    subscribe.setAttribute("aria-pressed", state.is_subscribed ? "true" : "false");
    paintStats(state.subscribers_count);
  }

  function paintHeader(next) {
    profile = next;
    const label = next.username || "Канал";
    name.textContent = label;
    avatar.textContent = label.slice(0, 1).toUpperCase();
    avatar.style.background = avatarColor(label);
    document.title = label;
    paintStats();
    paintSubscribe(null);
  }

  function selectTab(next) {
    tab = next;
    videos.hidden = tab !== "videos";
    playlists.hidden = tab !== "playlists";
    videoTab.classList.toggle("is-active", tab === "videos");
    playlistTab.classList.toggle("is-active", tab === "playlists");
    videoTab.setAttribute("aria-pressed", tab === "videos" ? "true" : "false");
    playlistTab.setAttribute("aria-pressed", tab === "playlists" ? "true" : "false");
  }

  async function loadVideos(current) {
    const items = await request(`/channels/${activeId}/videos?limit=50`);
    if (current !== ticket) {
      return;
    }
    videos.replaceChildren();
    if (!items.length) {
      status.textContent = "Публичных видео нет";
      return;
    }
    status.textContent = formatResultCount(items.length);
    for (const video of items) {
      videos.append(renderVideoCard(video, profile.username));
    }
  }

  async function loadPlaylists(current) {
    const items = await request(`/users/${activeId}/playlists`);
    if (current !== ticket) {
      return;
    }
    playlists.replaceChildren();
    if (!items.length) {
      status.textContent = "Плейлистов нет";
      return;
    }
    status.textContent = `${items.length} ${plural(items.length, "плейлист", "плейлиста", "плейлистов")}`;
    for (const playlist of items) {
      const item = document.createElement("article");
      item.className = "playlist";
      const title = document.createElement("h2");
      title.textContent = playlist.title;
      const meta = document.createElement("p");
      meta.className = "card-meta";
      const privacy = playlist.is_private ? "приватный" : "публичный";
      meta.textContent = `${privacy} · ${formatResultCount(playlist.videos_count)}`;
      item.append(title, meta);
      if (playlist.description) {
        const description = document.createElement("p");
        description.textContent = playlist.description;
        item.append(description);
      }
      playlists.append(item);
    }
  }

  async function loadTab() {
    const current = ticket;
    status.textContent = "Загрузка…";
    try {
      if (tab === "videos") {
        await loadVideos(current);
      } else {
        await loadPlaylists(current);
      }
    } catch (error) {
      if (current !== ticket) {
        return;
      }
      status.textContent = error.message || "Не удалось загрузить вкладку";
    }
  }

  async function open(userId) {
    const current = ++ticket;
    activeId = userId;
    profile = null;
    selectTab("videos");
    videos.replaceChildren();
    playlists.replaceChildren();
    name.textContent = "";
    stats.textContent = "";
    status.textContent = "Загрузка канала…";
    try {
      const next = await request(`/channels/${userId}`);
      if (current !== ticket) {
        return;
      }
      paintHeader(next);
      const user = currentUser();
      if (!user || user.id !== next.user_id) {
        const state = await request(`/users/${userId}/subscription`).catch(() => null);
        if (current === ticket && state) {
          paintSubscribe(state);
        }
      }
      await loadTab();
    } catch (error) {
      if (current !== ticket) {
        return;
      }
      status.textContent = error.status === 404 ? "Канал не найден" : (error.message || "Не удалось открыть канал");
    }
  }

  videoTab.addEventListener("click", () => {
    if (!activeId || tab === "videos") {
      return;
    }
    selectTab("videos");
    loadTab();
  });

  playlistTab.addEventListener("click", () => {
    if (!activeId || tab === "playlists") {
      return;
    }
    selectTab("playlists");
    loadTab();
  });

  subscribe.addEventListener("click", async () => {
    if (!profile) {
      return;
    }
    if (!currentUser()) {
      document.dispatchEvent(new CustomEvent("auth:open"));
      return;
    }
    subscribe.disabled = true;
    try {
      const state = await request(`/users/${profile.user_id}/subscribe`, { method: "POST" });
      paintSubscribe(state);
    } catch (error) {
      status.textContent = error.message || "Не удалось изменить подписку";
    } finally {
      subscribe.disabled = false;
    }
  });

  document.addEventListener("auth:changed", () => {
    if (profile && document.body.dataset.route === "channel") {
      paintSubscribe(null);
      request(`/users/${profile.user_id}/subscription`)
        .then((state) => {
          if (profile) {
            paintSubscribe(state);
          }
        })
        .catch(() => {});
    }
  });

  return { open };
}
