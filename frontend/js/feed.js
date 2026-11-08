import { request } from "./api.js";
import {
  avatarColor,
  formatDuration,
  formatPublished,
  formatResultCount,
  formatViews,
} from "./format.js";

const SELECTED_VIDEO_KEY = "yt.selectedVideoId";

const CATEGORIES = [
  { id: "all", label: "Все" },
  { id: "Tech", label: "Tech" },
  { id: "Gaming", label: "Gaming" },
  { id: "Music", label: "Music" },
  { id: "Education", label: "Education" },
];

const channelNames = new Map();

function selectedVideoId() {
  return localStorage.getItem(SELECTED_VIDEO_KEY) || "";
}

function rememberVideo(videoId) {
  localStorage.setItem(SELECTED_VIDEO_KEY, videoId);
}

async function fetchVideos(category, query) {
  const params = new URLSearchParams({ limit: "50" });
  const filtered = (category && category !== "all") || query;
  if (!filtered) {
    return request(`/videos?${params}`);
  }
  if (category && category !== "all") {
    params.set("category", category);
  }
  if (query) {
    params.set("query", query);
  }
  const page = await request(`/videos/search?${params}`);
  return page.items || [];
}

async function channelName(userId) {
  if (channelNames.has(userId)) {
    return channelNames.get(userId);
  }
  try {
    const profile = await request(`/channels/${userId}`);
    const name = profile.username || "Канал";
    channelNames.set(userId, name);
    return name;
  } catch {
    channelNames.set(userId, "Канал");
    return "Канал";
  }
}

function thumbnailPlaceholder(category) {
  const node = document.createElement("div");
  node.className = "thumb-fallback";
  node.textContent = category || "Видео";
  return node;
}

function renderCard(video, author) {
  const card = document.createElement("article");
  card.className = "card";
  if (video.id === selectedVideoId()) {
    card.classList.add("is-selected");
  }

  const link = document.createElement("a");
  link.className = "card-link";
  link.href = `#/watch/${video.id}`;
  link.dataset.videoId = video.id;
  link.addEventListener("click", () => {
    rememberVideo(video.id);
    document.querySelectorAll(".card.is-selected").forEach((node) => {
      node.classList.remove("is-selected");
    });
    card.classList.add("is-selected");
  });

  const thumb = document.createElement("div");
  thumb.className = "thumb";
  const image = document.createElement("img");
  image.alt = video.title;
  image.src = `/videos/${video.id}/thumbnail`;
  image.addEventListener("error", () => {
    image.replaceWith(thumbnailPlaceholder(video.category));
  });
  const duration = document.createElement("span");
  duration.className = "duration";
  duration.textContent = formatDuration(video.duration);
  thumb.append(image, duration);

  const body = document.createElement("div");
  body.className = "card-body";
  const avatar = document.createElement("span");
  avatar.className = "avatar";
  avatar.textContent = author.slice(0, 1).toUpperCase();
  avatar.style.background = avatarColor(author);

  const text = document.createElement("div");
  text.className = "card-text";
  const title = document.createElement("h3");
  title.className = "card-title";
  title.textContent = video.title;
  const channel = document.createElement("p");
  channel.className = "card-channel";
  channel.textContent = author;
  const meta = document.createElement("p");
  meta.className = "card-meta";
  const published = formatPublished(video.created_at);
  meta.textContent = published
    ? `${formatViews(video.views_count)} • ${published}`
    : formatViews(video.views_count);

  text.append(title, channel, meta);
  body.append(avatar, text);
  link.append(thumb, body);
  card.append(link);
  return card;
}

function renderSkeletons(grid) {
  grid.replaceChildren();
  for (let index = 0; index < 8; index += 1) {
    const card = document.createElement("div");
    card.className = "card skeleton";
    card.innerHTML = '<div class="thumb"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div>';
    grid.append(card);
  }
}

export function bindFeed() {
  const chips = document.querySelector("#chips");
  const grid = document.querySelector("#video-grid");
  const status = document.querySelector("#feed-status");
  const form = document.querySelector("#search-form");
  const input = document.querySelector("#search-input");
  const state = { category: "all", query: "" };

  function paintChips() {
    chips.replaceChildren();
    for (const category of CATEGORIES) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = category.label;
      button.dataset.category = category.id;
      const active = category.id === state.category;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
      button.addEventListener("click", () => {
        state.category = category.id;
        paintChips();
        load();
      });
      chips.append(button);
    }
  }

  async function load() {
    status.textContent = "Загрузка…";
    renderSkeletons(grid);
    try {
      const videos = await fetchVideos(state.category, state.query);
      const authors = await Promise.all(videos.map((video) => channelName(video.user_id)));
      grid.replaceChildren();
      videos.forEach((video, index) => {
        grid.append(renderCard(video, authors[index]));
      });
      status.textContent = videos.length ? formatResultCount(videos.length) : "Ничего не найдено";
    } catch (error) {
      grid.replaceChildren();
      status.textContent = error.status ? error.message : "Не удалось загрузить ленту";
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "chip";
      retry.textContent = "Повторить";
      retry.addEventListener("click", load);
      grid.append(retry);
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    state.query = input.value.trim();
    if (location.hash.startsWith("#/watch/")) {
      location.hash = "#/";
    }
    load();
  });

  const watchRoute = location.hash.match(/^#\/watch\/([0-9a-f-]{36})$/i);
  if (watchRoute) {
    rememberVideo(watchRoute[1]);
  }

  paintChips();
  load();
  return { reload: load };
}
