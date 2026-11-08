const TOKEN_KEY = "yt.accessToken";

export function authHeader() {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function messageFromBody(body, fallback) {
  const detail = body && body.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail) && detail[0] && typeof detail[0].msg === "string") {
    return detail[0].msg;
  }
  return fallback;
}

export async function request(path, options = {}) {
  const headers = { ...authHeader(), ...(options.headers || {}) };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let message = `Ошибка ${response.status}`;
    try {
      message = messageFromBody(await response.json(), message);
    } catch {
      /* The body is not JSON. */
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) {
    return null;
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }
  return response.json();
}
