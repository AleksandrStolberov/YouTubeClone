import { request } from "./api.js";
import { currentUser } from "./auth.js";

function formatDate(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function isStaff(user) {
  return Boolean(user && (user.role === "moderator" || user.role === "admin"));
}

export function bindModeration() {
  const list = document.querySelector("#report-list");
  const status = document.querySelector("#moderation-status");
  let ticket = 0;

  function clearEmpty() {
    if (!list.children.length) {
      status.textContent = "Нет жалоб на рассмотрении";
    }
  }

  async function act(report, kind, item) {
    const buttons = item.querySelectorAll("button");
    buttons.forEach((button) => {
      button.disabled = true;
    });
    try {
      if (kind === "ban") {
        await request(`/moderation/videos/${report.video_id}/ban`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: report.reason }),
        });
        list.querySelectorAll(`[data-video-id="${report.video_id}"]`).forEach((node) => {
          node.remove();
        });
      } else {
        await request(`/moderation/reports/${report.id}/reject`, { method: "POST" });
        item.remove();
      }
      clearEmpty();
    } catch (error) {
      buttons.forEach((button) => {
        button.disabled = false;
      });
      status.textContent = error.message || "Не удалось выполнить действие";
    }
  }

  function renderRow(report, video, reporter) {
    const item = document.createElement("article");
    item.className = "report";
    item.dataset.videoId = report.video_id;
    const title = document.createElement("a");
    title.className = "report-title";
    title.href = `#/watch/${report.video_id}`;
    title.textContent = video ? video.title : "Ролик недоступен";
    const reason = document.createElement("p");
    reason.textContent = report.reason;
    const meta = document.createElement("p");
    meta.className = "report-meta";
    const who = reporter && reporter.username ? reporter.username : "Пользователь";
    meta.textContent = `${who} · ${formatDate(report.created_at)}`;
    const actions = document.createElement("div");
    actions.className = "report-actions";
    const ban = document.createElement("button");
    ban.type = "button";
    ban.textContent = "Заблокировать видео";
    ban.addEventListener("click", () => {
      act(report, "ban", item);
    });
    const reject = document.createElement("button");
    reject.type = "button";
    reject.textContent = "Отклонить жалобу";
    reject.addEventListener("click", () => {
      act(report, "reject", item);
    });
    actions.append(ban, reject);
    item.append(title, reason, meta, actions);
    return item;
  }

  async function open() {
    const current = ++ticket;
    document.title = "Модерация";
    const user = currentUser();
    list.replaceChildren();
    if (!isStaff(user)) {
      status.textContent = "Панель доступна модераторам и администраторам. Войдите под подходящей учётной записью.";
      return;
    }
    status.textContent = "Загрузка жалоб…";
    try {
      const reports = await request("/moderation/reports?status=pending");
      if (current !== ticket) {
        return;
      }
      const rows = await Promise.all(reports.map(async (report) => {
        const [video, reporter] = await Promise.all([
          request(`/videos/${report.video_id}`).catch(() => null),
          request(`/channels/${report.reporter_id}`).catch(() => null),
        ]);
        return { report, video, reporter };
      }));
      if (current !== ticket) {
        return;
      }
      list.replaceChildren();
      if (!rows.length) {
        status.textContent = "Нет жалоб на рассмотрении";
        return;
      }
      status.textContent = "";
      for (const row of rows) {
        list.append(renderRow(row.report, row.video, row.reporter));
      }
    } catch (error) {
      if (current !== ticket) {
        return;
      }
      status.textContent = error.message || "Не удалось загрузить жалобы";
    }
  }

  document.addEventListener("auth:changed", () => {
    if (document.body.dataset.route === "moderation") {
      open();
    }
  });

  return { open };
}
