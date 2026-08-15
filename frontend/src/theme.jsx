import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { Moon, Sun } from "lucide-react";

const STORAGE_KEY = "rc_theme";
const ThemeContext = createContext(null);

function savedTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(savedTheme);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      theme === "dark" ? "#0B0C0F" : "#F7F9FD",
    );
    try { localStorage.setItem(STORAGE_KEY, theme); } catch { /* storage can be disabled */ }
  }, [theme]);

  const value = useMemo(() => ({
    theme,
    isDark: theme === "dark",
    setTheme,
    toggleTheme: () => setTheme((current) => current === "dark" ? "light" : "dark"),
  }), [theme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}

export function ThemeToggleButton({ className = "" }) {
  const { isDark, toggleTheme } = useTheme();
  const next = isDark ? "light" : "dark";
  return (
    <button className={`iconbtn theme-toggle ${className}`} title={`Switch to ${next} mode`}
      aria-label={`Switch to ${next} mode`} aria-pressed={isDark} onClick={toggleTheme}>
      {isDark ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}
