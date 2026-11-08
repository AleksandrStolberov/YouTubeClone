const AVATAR_COLORS = ["#c2185b", "#6a1b9a", "#1565c0", "#00695c", "#ef6c00", "#455a64"];

export function plural(count, one, few, many) {
  const abs = Math.abs(count) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) {
    return many;
  }
  if (last > 1 && last < 5) {
    return few;
  }
  if (last === 1) {
    return one;
  }
  return many;
}

export function formatViews(count) {
  const value = Number(count) || 0;
  if (value >= 1000) {
    const compact = new Intl.NumberFormat("ru-RU", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
    return `${compact} просмотров`;
  }
  return `${value} ${plural(value, "просмотр", "просмотра", "просмотров")}`;
}

export function formatPublished(iso) {
  const published = new Date(iso);
  if (Number.isNaN(published.getTime())) {
    return "";
  }
  const seconds = Math.max(0, (Date.now() - published.getTime()) / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const months = Math.floor(days / 30);
  const years = Math.floor(days / 365);
  if (years >= 1) {
    return `${years} ${plural(years, "год", "года", "лет")} назад`;
  }
  if (months >= 1) {
    return `${months} ${plural(months, "месяц", "месяца", "месяцев")} назад`;
  }
  if (days >= 7) {
    const weeks = Math.floor(days / 7);
    return `${weeks} ${plural(weeks, "неделю", "недели", "недель")} назад`;
  }
  if (days >= 1) {
    return `${days} ${plural(days, "день", "дня", "дней")} назад`;
  }
  if (hours >= 1) {
    return `${hours} ${plural(hours, "час", "часа", "часов")} назад`;
  }
  if (minutes >= 1) {
    return `${minutes} ${plural(minutes, "минуту", "минуты", "минут")} назад`;
  }
  return "только что";
}

export function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  const clock = `${minutes}:${String(rest).padStart(2, "0")}`;
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}` : clock;
}

export function formatSubscribers(count) {
  const value = Number(count) || 0;
  return `${value} ${plural(value, "подписчик", "подписчика", "подписчиков")}`;
}

export function formatResultCount(count) {
  return `${count} ${plural(count, "ролик", "ролика", "роликов")}`;
}

export function avatarColor(name) {
  let hash = 0;
  for (const char of name || "?") {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

export function roleLabel(role) {
  if (role === "admin") {
    return "администратор";
  }
  if (role === "moderator") {
    return "модератор";
  }
  if (role === "user") {
    return "пользователь";
  }
  return "без входа";
}
