import { authHeader } from "./api.js";
import { currentUser } from "./auth.js";

function errorMessage(xhr) {
  try {
    const body = JSON.parse(xhr.responseText);
    if (typeof body.detail === "string" && body.detail.trim()) {
      return body.detail;
    }
    if (Array.isArray(body.detail) && body.detail[0] && body.detail[0].msg) {
      return body.detail[0].msg;
    }
  } catch {
    /* The body is not JSON. */
  }
  return `Ошибка ${xhr.status || "сети"}`;
}

export function bindUpload() {
  const dialog = document.querySelector("#upload-dialog");
  const form = document.querySelector("#upload-form");
  const guest = document.querySelector("#upload-guest");
  const progress = document.querySelector("#upload-progress");
  const bar = document.querySelector("#upload-bar");
  const percent = document.querySelector("#upload-percent");
  const error = document.querySelector("#upload-error");
  const submit = document.querySelector("#upload-submit");

  function syncAccess() {
    const signedIn = Boolean(currentUser());
    form.hidden = !signedIn;
    guest.hidden = signedIn;
  }

  function open() {
    syncAccess();
    error.textContent = "";
    percent.textContent = "";
    progress.hidden = true;
    bar.style.width = "0";
    if (!dialog.open) {
      dialog.showModal();
    }
  }

  function close() {
    if (dialog.open) {
      dialog.close();
    }
  }

  document.querySelector("#create-button").addEventListener("click", () => {
    if (!currentUser()) {
      document.dispatchEvent(new CustomEvent("auth:open"));
      return;
    }
    if (location.hash !== "#/upload") {
      location.hash = "#/upload";
      return;
    }
    open();
  });

  document.querySelector("#upload-signin").addEventListener("click", () => {
    document.dispatchEvent(new CustomEvent("auth:open"));
  });

  document.querySelector("#upload-cancel").addEventListener("click", () => {
    close();
    if (location.hash === "#/upload") {
      location.hash = "#/";
    }
  });

  dialog.addEventListener("close", () => {
    submit.disabled = false;
  });

  document.addEventListener("auth:changed", () => {
    if (dialog.open) {
      syncAccess();
    }
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!currentUser()) {
      document.dispatchEvent(new CustomEvent("auth:open"));
      return;
    }
    const video = document.querySelector("#upload-video").files[0];
    if (!video) {
      error.textContent = "Выберите видеофайл";
      return;
    }
    const videoName = video.name.toLowerCase();
    if (!videoName.endsWith(".mp4") && !videoName.endsWith(".webm")) {
      error.textContent = "Поддерживаются файлы mp4 и webm";
      return;
    }
    const title = document.querySelector("#upload-title").value.trim();
    if (!title) {
      error.textContent = "Укажите заголовок";
      return;
    }
    const cover = document.querySelector("#upload-cover").files[0];
    if (cover) {
      const coverName = cover.name.toLowerCase();
      if (!coverName.endsWith(".jpg") && !coverName.endsWith(".jpeg") && !coverName.endsWith(".png")) {
        error.textContent = "Обложка должна быть jpg или png";
        return;
      }
    }

    const body = new FormData();
    body.append("video", video);
    body.append("title", title);
    const description = document.querySelector("#upload-description").value.trim();
    if (description) {
      body.append("description", description);
    }
    body.append("category", document.querySelector("#upload-category").value);
    const tags = document.querySelector("#upload-tags").value.trim();
    if (tags) {
      body.append("tags", tags);
    }
    if (cover) {
      body.append("thumbnail", cover);
    }
    body.append("is_private", document.querySelector("#upload-private").checked ? "true" : "false");

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/videos/upload");
    const headers = authHeader();
    if (headers.Authorization) {
      xhr.setRequestHeader("Authorization", headers.Authorization);
    }
    progress.hidden = false;
    bar.style.width = "0";
    percent.textContent = "0%";
    error.textContent = "";
    submit.disabled = true;
    xhr.upload.onprogress = (progressEvent) => {
      if (!progressEvent.lengthComputable) {
        return;
      }
      const value = Math.round((progressEvent.loaded / progressEvent.total) * 100);
      bar.style.width = `${value}%`;
      percent.textContent = `${value}%`;
    };
    xhr.onload = () => {
      submit.disabled = false;
      if (xhr.status >= 200 && xhr.status < 300) {
        const created = JSON.parse(xhr.responseText);
        form.reset();
        close();
        location.hash = `#/watch/${created.id}`;
        return;
      }
      error.textContent = errorMessage(xhr);
    };
    xhr.onerror = () => {
      submit.disabled = false;
      error.textContent = "Не удалось загрузить видео";
    };
    xhr.send(body);
  });

  return { open, close };
}
