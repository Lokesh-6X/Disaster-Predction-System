import { createContext, useContext, useEffect, useMemo, useState } from 'react';

// Theme mode: 'system' follows the OS; 'light'/'dark' are explicit. Saved per browser.
const ThemeContext = createContext(null);
const STORAGE_KEY = 'theme';
const MODES = ['system', 'light', 'dark'];

function systemPrefersDark() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
}

export function ThemeProvider({ children }) {
  const [mode, setMode] = useState(() => {
    try {
      return MODES.includes(localStorage.getItem(STORAGE_KEY)) ? localStorage.getItem(STORAGE_KEY) : 'system';
    } catch {
      return 'system';
    }
  });
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!media) return undefined;
    const update = () => setSystemDark(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  const theme = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      /* storage unavailable */
    }
  }, [theme, mode]);

  const value = useMemo(
    () => ({ mode, theme, cycle: () => setMode((m) => MODES[(MODES.indexOf(m) + 1) % MODES.length]) }),
    [mode, theme],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}

/** Resolved CSS colour tokens, recomputed when the theme changes (for charts). */
export function useColors(names) {
  const { theme } = useTheme();
  const key = names.join(',');
  return useMemo(() => {
    const style = getComputedStyle(document.documentElement);
    return Object.fromEntries(key.split(',').map((n) => [n, style.getPropertyValue(`--${n}`).trim()]));
  }, [theme, key]);
}
