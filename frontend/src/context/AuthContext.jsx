import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, setToken, setUnauthorizedHandler } from '../api/client.js';

// The token lives in memory and sessionStorage (cleared when the tab closes).
const STORAGE_KEY = 'skywatch.session';
const AuthContext = createContext(null);

function loadSession() {
  try {
    const session = JSON.parse(sessionStorage.getItem(STORAGE_KEY));
    if (session && new Date(session.expires_at) > new Date()) return session;
  } catch {
    /* no or bad session */
  }
  return null;
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => {
    const saved = loadSession();
    setToken(saved?.access_token ?? null);
    return saved;
  });
  const [notice, setNotice] = useState(null);

  const logout = useCallback((message = null) => {
    setToken(null);
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    setSession(null);
    setNotice(message);
  }, []);

  const login = useCallback(async (username, password) => {
    const result = await api.post('/api/auth/login', { username, password });
    setToken(result.access_token);
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(result));
    } catch {
      /* storage unavailable: session lasts until reload */
    }
    setNotice(null);
    setSession(result);
  }, []);

  // Any 401 from the API, or the token's expiry time, ends the session
  useEffect(() => {
    setUnauthorizedHandler(() => logout('Your session has expired. Please sign in again.'));
  }, [logout]);

  useEffect(() => {
    if (!session) return undefined;
    const remaining = new Date(session.expires_at).getTime() - Date.now();
    const timer = setTimeout(
      () => logout('Your session has expired. Please sign in again.'),
      Math.max(0, Math.min(remaining, 2 ** 31 - 1)),
    );
    return () => clearTimeout(timer);
  }, [session, logout]);

  const value = useMemo(
    () => ({ session, user: session?.user ?? null, login, logout, notice }),
    [session, login, logout, notice],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
