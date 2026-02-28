const THEME_KEY = "localforge_theme";

export type Theme = "dark" | "light";

export function getStoredTheme(): Theme {
  return (localStorage.getItem(THEME_KEY) as Theme) ?? "dark";
}

export function setTheme(theme: Theme) {
  localStorage.setItem(THEME_KEY, theme);
  if (theme === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

export function initTheme() {
  setTheme(getStoredTheme());
}
