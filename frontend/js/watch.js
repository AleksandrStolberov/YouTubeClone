import { request } from "./api.js";
import { currentUser } from "./auth.js";
import {
  avatarColor,
  formatPublished,
  formatSubscribers,
  formatViews,
} from "./format.js";

const SELECTED_VIDEO_KEY = "yt.selectedVideoId";

function countLabel(value) {
  return new Intl.NumberFormat("ru-RU").format(Number(value) || 0);
}

function canDelete(comment, user) {
  if (!user) {
    return false;
  }
  if (user.id === comment.user_id) {
    return true;
  }
  return user.role === "admin" || user.role === "moderator";
}

async function settle(promise, fallback) {
  try {
    return await promise;
  } catch {
    return fallback;
  }
}

export function bindWatch() {
  const screen = document.querySelector("#watch");
  const player = document.querySelector("#player");
  const likeButton = document.querySelector("#like-button");
  const dislikeButton = document.querySelector("#dislike-button");
  const subscribeButton = document.querySelector("#subscribe-button");
  const commentForm = document.querySelector("#comment-form");
  const commentInput = document.querySelector("#comment-input");
  const reportDialog = document.querySelector("#report-dialog");
  const reportForm = document.querySelector("#report-form");
  const reportCustom = document.querySelector("#report-custom");
  const reportError = document.querySelector("#report-error");

  let ticket = 0;
  let activeId = "";
  let activeVideo = null;

  function setStatus(text) {
    document.querySelector("#watch-status").textContent = text || "";
  }

  function paintMeta(video) {
    const published = formatPublished(video.created_at);
    const views = formatViews(video.views_count);
    document.querySelector("#watch-meta").textContent = published ? `${views} • ${published}` : views;
  }

  function paintVideo(video) {
    document.querySelector("#watch-title").textContent = video.title;
    document.title = `${video.title} — YouTube Clone`;
    paintMeta(video);
    const description = document.querySelector("#watch-description");
    description.textContent = video.description || "";
    description.hidden = !video.description;
  }

  function paintReactions(summary) {
    document.querySelector("#like-count").textContent = countLabel(summary.likes_count);
    document.querySelector("#dislike-count").textContent = countLabel(summary.dislikes_count);
    likeButton.classList.toggle("is-active", summary.user_reaction === true);
    dislikeButton.classList.toggle("is-active", summary.user_reaction === false);
    likeButton.setAttribute("aria-pressed", summary.user_reaction === true ? "true" : "false");
    dislikeButton.setAttribute("aria-pressed", summary.user_reaction === false ? "true" : "false");
  }

  function paintSubscription(state, user) {
    document.querySelector("#channel-subs").textContent = formatSubscribers(state.subscribers_count);
    const ownChannel = Boolean(user && activeVideo && user.id === activeVideo.user_id);
    subscribeButton.hidden = ownChannel;
    subscribeButton.textContent = state.is_subscribed ? "Вы подписаны" : "Подписаться";
    subscribeButton.classList.toggle("is-subscribed", Boolean(state.is_subscribed));
    subscribeButton.setAttribute("aria-pressed", state.is_subscribed ? "true" : "false");
  }

  function paintChannel(channel, subscription, user) {
    const name = channel.username || "Канал";
    const href = activeVideo ? `#/channel/${activeVideo.user_id}` : "#/";
    const nameLink = document.querySelector("#channel-name");
    nameLink.textContent = name;
    nameLink.href = href;
    document.querySelector("#channel-link").href = href;
    const avatar = document.querySelector("#channel-avatar");
    avatar.textContent = name.slice(0, 1).toUpperCase();
    avatar.style.background = avatarColor(name);
    paintSubscription(subscription, user);
  }

  function renderComment(comment, user) {
    const item = document.createElement("article");
    item.className = "comment";
    const avatar = document.createElement("span");
    avatar.className = "avatar";
    avatar.textContent = (comment.author_username || "?").slice(0, 1).toUpperCase();
    avatar.style.background = avatarColor(comment.author_username);
    const body = document.createElement("div");
    const head = document.createElement("p");
    head.className = "comment-head";
    const name = document.createElement("strong");
    name.textContent = comment.author_username;
    const time = document.createElement("span");
    time.textContent = formatPublished(comment.created_at);
    head.append(name, time);
    const text = document.createElement("p");
    text.className = "comment-text";
    text.textContent = comment.text;
    body.append(head, text);
    if (canDelete(comment, user)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "link-button";
      button.textContent = "Удалить";
      button.addEventListener("click", () => {
        removeComment(comment.id, item);
      });
      body.append(button);
    }
    item.append(avatar, body);
    return item;
  }

  function paintComments(comments, user) {
    document.querySelector("#comments-heading").textContent = `Комментарии · ${comments.length}`;
    commentForm.hidden = !user;
    document.querySelector("#comment-hint").textContent = user ? "" : "Войдите, чтобы оставить комментарий";
    const list = document.querySelector("#comment-list");
    list.replaceChildren();
    comments.forEach((comment) => {
      list.append(renderComment(comment, user));
    });
  }

  function renderRecommendation(video, author) {
    const link = document.createElement("a");
    link.className = "recommend";
    link.href = `#/watch/${video.id}`;
    const thumb = document.createElement("div");
    thumb.className = "thumb";
    const image = document.createElement("img");
    image.alt = "";
    image.src = `/videos/${video.id}/thumbnail`;
    image.addEventListener("error", () => {
      image.replaceWith(Object.assign(document.createElement("div"), {
        className: "thumb-fallback",
        textContent: video.category || "Видео",
      }));
    });
    thumb.append(image);
    const text = document.createElement("div");
    const title = document.createElement("p");
    title.className = "recommend-title";
    title.textContent = video.title;
    const meta = document.createElement("p");
    meta.className = "recommend-meta";
    meta.textContent = `${author} • ${formatViews(video.views_count)}`;
    text.append(title, meta);
    link.append(thumb, text);
    return link;
  }

  async function paintRecommendations(videos) {
    const root = document.querySelector("#recommendations");
    const current = ticket;
    root.replaceChildren();
    const heading = document.createElement("h2");
    heading.textContent = "Рекомендации";
    root.append(heading);
    if (!videos.length) {
      const empty = document.createElement("p");
      empty.className = "watch-meta";
      empty.textContent = "Других роликов нет";
      root.append(empty);
      return;
    }
    const names = new Map();
    await Promise.all([...new Set(videos.map((video) => video.user_id))].map(async (userId) => {
      const profile = await settle(request(`/channels/${userId}`), null);
      names.set(userId, profile && profile.username ? profile.username : "Канал");
    }));
    if (current !== ticket) {
      return;
    }
    videos.forEach((video) => {
      root.append(renderRecommendation(video, names.get(video.user_id) || "Канал"));
    });
  }

  async function removeComment(commentId, item) {
    try {
      await request(`/comments/${commentId}`, { method: "DELETE" });
      item.remove();
      const count = document.querySelector("#comment-list").children.length;
      document.querySelector("#comments-heading").textContent = `Комментарии · ${count}`;
    } catch (error) {
      setStatus(error.message || "Не удалось удалить комментарий");
    }
  }

  async function refreshInteractions() {
    const current = ticket;
    const videoId = activeId;
    const authorId = activeVideo && activeVideo.user_id;
    if (!videoId || !authorId) {
      return;
    }
    const [reactions, comments, subscription] = await Promise.all([
      settle(request(`/videos/${videoId}/reactions`), null),
      settle(request(`/videos/${videoId}/comments?limit=100`), null),
      settle(request(`/users/${authorId}/subscription`), null),
    ]);
    if (current !== ticket) {
      return;
    }
    if (reactions) {
      paintReactions(reactions);
    }
    if (comments) {
      paintComments(comments, currentUser());
    }
    if (subscription) {
      paintSubscription(subscription, currentUser());
    }
  }

  function closePlayer() {
    player.pause();
    player.removeAttribute("src");
    player.load();
  }

  function close() {
    ticket += 1;
    activeId = "";
    activeVideo = null;
    closePlayer();
    screen.hidden = true;
    document.title = "YouTube Clone";
  }

  async function open(videoId) {
    const current = ++ticket;
    activeId = videoId;
    activeVideo = null;
    localStorage.setItem(SELECTED_VIDEO_KEY, videoId);
    screen.hidden = false;
    document.body.dataset.route = "watch";
    setStatus("Загрузка…");
    closePlayer();
    document.querySelector("#comment-list").replaceChildren();
    document.querySelector("#recommendations").replaceChildren();

    let video;
    try {
      video = await request(`/videos/${videoId}`);
    } catch (error) {
      if (current !== ticket) {
        return;
      }
      setStatus(error.status ? error.message : "Не удалось открыть ролик");
      return;
    }
    if (current !== ticket) {
      return;
    }

    activeVideo = video;
    paintVideo(video);
    player.src = `/videos/${videoId}/stream`;
    player.play().catch(() => {});

    const [viewed, reactions, comments, channel, subscription, catalog] = await Promise.all([
      settle(request(`/videos/${videoId}/view`, { method: "POST" }), null),
      settle(request(`/videos/${videoId}/reactions`), { likes_count: 0, dislikes_count: 0, user_reaction: null }),
      settle(request(`/videos/${videoId}/comments?limit=100`), []),
      settle(request(`/channels/${video.user_id}`), { username: "Канал", subscribers_count: 0 }),
      settle(request(`/users/${video.user_id}/subscription`), {
        is_subscribed: false,
        subscribers_count: 0,
      }),
      settle(request("/videos?limit=50"), []),
    ]);
    if (current !== ticket) {
      return;
    }
    if (viewed && typeof viewed.views_count === "number") {
      video.views_count = viewed.views_count;
      paintMeta(video);
    }
    paintChannel(channel, subscription, currentUser());
    paintReactions(reactions);
    paintComments(comments, currentUser());
    await paintRecommendations(catalog.filter((item) => item.id !== videoId));
    if (current === ticket) {
      setStatus("");
    }
  }

  likeButton.addEventListener("click", () => {
    sendReaction(true);
  });
  dislikeButton.addEventListener("click", () => {
    sendReaction(false);
  });
  subscribeButton.addEventListener("click", toggleSubscription);
  commentForm.addEventListener("submit", submitComment);
  document.querySelector("#report-button").addEventListener("click", openReport);
  document.querySelector("#report-cancel").addEventListener("click", () => {
    reportDialog.close();
  });
  reportForm.addEventListener("submit", submitReport);
  player.addEventListener("error", () => {
    if (!activeId || !player.getAttribute("src")) {
      return;
    }
    setStatus("Не удалось воспроизвести видео");
  });
  document.addEventListener("auth:changed", () => {
    refreshInteractions();
  });

  async function sendReaction(isLike) {
    const videoId = activeId;
    if (!videoId) {
      return;
    }
    if (!currentUser()) {
      setStatus("Войдите, чтобы оценить ролик");
      return;
    }
    likeButton.disabled = true;
    dislikeButton.disabled = true;
    try {
      const summary = await request(`/videos/${videoId}/reaction`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_like: isLike }),
      });
      if (videoId !== activeId) {
        return;
      }
      paintReactions(summary);
      setStatus("");
    } catch (error) {
      setStatus(error.message || "Не удалось сохранить реакцию");
    } finally {
      likeButton.disabled = false;
      dislikeButton.disabled = false;
    }
  }

  async function toggleSubscription() {
    const videoId = activeId;
    const authorId = activeVideo && activeVideo.user_id;
    if (!videoId || !authorId) {
      return;
    }
    if (!currentUser()) {
      setStatus("Войдите, чтобы подписаться");
      return;
    }
    subscribeButton.disabled = true;
    try {
      const state = await request(`/users/${authorId}/subscribe`, { method: "POST" });
      if (videoId !== activeId) {
        return;
      }
      paintSubscription(state, currentUser());
      setStatus("");
    } catch (error) {
      setStatus(error.message || "Не удалось изменить подписку");
    } finally {
      subscribeButton.disabled = false;
    }
  }

  async function submitComment(event) {
    event.preventDefault();
    const user = currentUser();
    if (!activeId || !user) {
      setStatus("Войдите, чтобы оставить комментарий");
      return;
    }
    const videoId = activeId;
    const text = commentInput.value.trim();
    if (!text) {
      return;
    }
    try {
      const created = await request(`/videos/${videoId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (videoId !== activeId) {
        return;
      }
      commentInput.value = "";
      document.querySelector("#comment-list").prepend(renderComment(created, user));
      const count = document.querySelector("#comment-list").children.length;
      document.querySelector("#comments-heading").textContent = `Комментарии · ${count}`;
      setStatus("");
    } catch (error) {
      setStatus(error.message || "Не удалось отправить комментарий");
    }
  }

  function openReport() {
    if (!currentUser()) {
      setStatus("Войдите, чтобы отправить жалобу");
      return;
    }
    reportError.textContent = "";
    reportCustom.value = "";
    const preset = reportForm.querySelector('input[value="Спам"]');
    if (preset) {
      preset.checked = true;
    }
    reportDialog.showModal();
  }

  async function submitReport(event) {
    event.preventDefault();
    if (!activeId || !currentUser()) {
      return;
    }
    const selected = reportForm.querySelector('input[name="reason"]:checked');
    const reason = selected && selected.value === "custom"
      ? reportCustom.value.trim()
      : (selected ? selected.value : "");
    if (!reason) {
      reportError.textContent = "Укажите причину";
      return;
    }
    try {
      await request(`/videos/${activeId}/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      reportDialog.close();
      setStatus("Жалоба отправлена");
    } catch (error) {
      reportError.textContent = error.message || "Не удалось отправить жалобу";
    }
  }

  return { open, close };
}
