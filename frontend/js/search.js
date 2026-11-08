import { request } from "./api.js";
import {
  avatarColor,
  formatPublished,
  formatResultCount,
  formatViews,
} from "./format.js";

const channelNames = new Map();

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
    return "Канал";
  }
}

function thumbnail(video) {
  const thumb = document.createElement("div");
  thumb.className = "thumb";
  const image = document.createElement("img");
  image.alt = video.title;
  image.src = `/videos/${video.id}/thumbnail`;
  image.addEventListener("error", () => {
    const fallback = document.createElement("div");
    fallback.className = "thumb-fallback";
    fallback.textContent = video.category || "Видео";
    image.replaceWith(fallback);
  });
  thumb.append(image);
  return thumb;
}

function renderResult(video, author) {
  const card = document.createElement("article");
  card.className = "search-card";
  const media = document.createElement("a");
  media.className = "card-link";
  media.href = `#/watch/${video.id}`;
  media.append(thumbnail(video));
  const body = document.createElement("div");
  const title = document.createElement("a");
  title.className = "search-title";
  title.href = `#/watch/${video.id}`;
  title.textContent = video.title;
  const channel = document.createElement("a");
  channel.className = "card-channel";
  channel.href = `#/channel/${video.user_id}`;
  const avatar = document.createElement("span");
  avatar.className = "avatar";
  avatar.textContent = author.slice(0, 1).toUpperCase();
  avatar.style.background = avatarColor(author);
  const label = document.createElement("span");
  label.textContent = author;
  channel.append(avatar, label);
  const description = document.createElement("p");
  description.className = "search-description";
  description.textContent = video.description || "";
  const meta = document.createElement("p");
  meta.className = "card-meta";
  const published = formatPublished(video.created_at);
  meta.textContent = published
    ? `${formatViews(video.views_count)} · ${published}`
    : formatViews(video.views_count);
  body.append(title, channel, description, meta);
  card.append(media, body);
  return card;
}

export function bindSearch() {
  const form = document.querySelector("#search-form");
  const input = document.querySelector("#search-input");
  const heading = document.querySelector("#search-heading");
  const status = document.querySelector("#search-status");
  const results = document.querySelector("#search-results");
  let ticket = 0;

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = input.value.trim();
    const next = query ? `#/search?q=${encodeURIComponent(query)}` : "#/search";
    if (location.hash === next) {
      open(query);
      return;
    }
    location.hash = next;
  });

  async function open(query) {
    const current = ++ticket;
    const text = (query || "").trim();
    input.value = text;
    document.title = text ? `Поиск: ${text}` : "Поиск";
    heading.textContent = text ? `Поиск: ${text}` : "Поиск";
    results.replaceChildren();
    if (!text) {
      status.textContent = "Введите запрос в строке поиска";
      return;
    }
    status.textContent = "Поиск…";
    try {
      const page = await request(`/videos/search?${new URLSearchParams({ query: text, limit: "50" })}`);
      if (current !== ticket) {
        return;
      }
      const items = page.items || [];
      const authors = await Promise.all(items.map((video) => channelName(video.user_id)));
      if (current !== ticket) {
        return;
      }
      results.replaceChildren();
      if (!items.length) {
        status.textContent = "Ничего не найдено";
        return;
      }
      status.textContent = formatResultCount(items.length);
      items.forEach((video, index) => {
        results.append(renderResult(video, authors[index]));
      });
    } catch (error) {
      if (current !== ticket) {
        return;
      }
      status.textContent = error.message || "Не удалось выполнить поиск";
    }
  }

  return { open };
}
