import { request } from "./api.js";
import { avatarColor, roleLabel } from "./format.js";

const ACCESS_KEY = "yt.accessToken";
const REFRESH_KEY = "yt.refreshToken";
const USER_KEY = "yt.user";

const DEMO_USERS = [
  { username: "admin", password: "Admin123!", label: "admin" },
  { username: "moderator", password: "Moderator123!", label: "moderator" },
  { username: "user1", password: "User1123!", label: "user1" },
  { username: "user2", password: "User2123!", label: "user2" },
];

function readUser() {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function clearSession() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

function setStatus(text) {
  const node = document.querySelector("#auth-status");
  node.textContent = text || "";
}

function publish(user) {
  paintAccount(user);
  document.dispatchEvent(new CustomEvent("auth:changed", { detail: user }));
}

export function currentUser() {
  return readUser();
}

function paintAccount(user) {
  const name = document.querySelector("#account-name");
  const role = document.querySelector("#account-role");
  const avatar = document.querySelector("#account-avatar");
  const label = user ? user.username : "Гость";
  name.textContent = label;
  role.textContent = roleLabel(user ? user.role : null);
  avatar.textContent = label.slice(0, 1).toUpperCase();
  avatar.style.background = avatarColor(label);
  document.querySelectorAll(".demo-button").forEach((button) => {
    const guest = button.dataset.guest === "true";
    const active = user ? button.dataset.username === user.username : guest;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function setBusy(busy) {
  document.querySelectorAll(".demo-button").forEach((button) => {
    button.disabled = busy;
  });
}

async function signIn(account) {
  setBusy(true);
  setStatus(`Вход: ${account.label}…`);
  try {
    const tokens = await request("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: account.username,
        password: account.password,
      }),
    });
    localStorage.setItem(ACCESS_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
    const me = await request("/auth/me");
    localStorage.setItem(USER_KEY, JSON.stringify(me));
    publish(me);
    setStatus("");
  } catch (error) {
    clearSession();
    publish(null);
    const known = !error.status
      ? "Сервер недоступен"
      : error.status === 401
        ? "Неверный логин или пароль"
        : error.message;
    setStatus(known || "Не удалось войти");
  } finally {
    setBusy(false);
  }
}

function signOut() {
  clearSession();
  publish(null);
  setStatus("");
}

export function bindAuth() {
  const root = document.querySelector("#demo-users");
  for (const account of DEMO_USERS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "demo-button";
    button.dataset.username = account.username;
    button.textContent = account.label;
    button.addEventListener("click", () => {
      signIn(account);
    });
    root.append(button);
  }

  const guest = document.createElement("button");
  guest.type = "button";
  guest.className = "demo-button";
  guest.dataset.guest = "true";
  guest.textContent = "Гость";
  guest.addEventListener("click", signOut);
  root.append(guest);

  paintAccount(readUser());
  restoreSession();
}

async function restoreSession() {
  if (!localStorage.getItem(ACCESS_KEY)) {
    paintAccount(null);
    return;
  }
  try {
    const me = await request("/auth/me");
    localStorage.setItem(USER_KEY, JSON.stringify(me));
    publish(me);
  } catch {
    clearSession();
    publish(null);
    setStatus("Сессия истекла. Войдите снова.");
  }
}
