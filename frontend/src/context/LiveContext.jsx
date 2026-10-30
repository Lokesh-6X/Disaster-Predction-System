import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api, liveSocketUrl, query } from '../api/client.js';
import { DEFAULT_TZ } from '../utils/format.js';
import { useAuth } from './AuthContext.jsx';

// Shared live state for all pages: system info, the kit, latest reading and
// predictions. Updates arrive over the WebSocket; while it is down, the data
// is polled every 30 s instead.
const LiveContext = createContext(null);
const RECONNECT_DELAYS_S = [1, 2, 5, 10, 30];
const POLL_MS = 30_000;
const TOAST_MS = 15_000;
const UNAUTHORIZED = 4401;

export function LiveProvider({ children }) {
  const { session, logout } = useAuth();
  const [system, setSystem] = useState(null);
  const [kit, setKit] = useState(null);
  const [reading, setReading] = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [alertCount, setAlertCount] = useState(0);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const [toasts, setToasts] = useState([]);
  const listeners = useRef(new Set());
  const kitRef = useRef(null);

  const loadKitData = useCallback(async (kitId) => {
    const [latest, predicted] = await Promise.all([
      api.get(`/api/readings/latest${query({ kit_id: kitId })}`),
      api.get(`/api/predictions/latest${query({ kit_id: kitId })}`),
    ]);
    setReading(latest.reading);
    setPredictions(predicted);
  }, []);

  const loadAlertCount = useCallback(async () => {
    const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    const alerts = await api.get(`/api/alerts${query({ from: since, page_size: 1 })}`);
    setAlertCount(alerts.total);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [sys, kits] = await Promise.all([api.get('/api/system'), api.get('/api/kits')]);
      setSystem(sys);
      const first = kits.items[0] ?? null;
      kitRef.current = first;
      setKit(first);
      if (first) await loadKitData(first.kit_id);
      await loadAlertCount();
      setError(null);
    } catch (err) {
      if (err.status !== 401) setError(err.message);
    }
  }, [loadKitData, loadAlertCount]);

  const dismissToast = useCallback((id) => setToasts((list) => list.filter((t) => t.id !== id)), []);

  const handleMessage = useCallback(
    async ({ type, data }) => {
      listeners.current.forEach((listener) => listener(type, data));
      const kitId = kitRef.current?.kit_id;
      if (type === 'reading' && data.kit_id === kitId) {
        setKit((k) => (k ? { ...k, last_seen: data.received_at, status: 'online' } : k));
        const latest = await api.get(`/api/readings/latest${query({ kit_id: kitId })}`);
        setReading(latest.reading);
      } else if (type === 'kit_status' && data.kit_id === kitId) {
        setKit((k) => (k ? { ...k, status: data.status } : k));
      } else if (type === 'prediction') {
        await loadKitData(kitId);
        setSystem(await api.get('/api/system'));
      } else if (type === 'alert') {
        setAlertCount((n) => n + 1);
        const id = `${data.id}-${Date.now()}`;
        setToasts((list) => [...list, { id, ...data }]);
        setTimeout(() => dismissToast(id), TOAST_MS);
      }
    },
    [loadKitData, dismissToast],
  );

  // Initial load and WebSocket connection while logged in
  useEffect(() => {
    if (!session) return undefined;
    let socket = null;
    let attempt = 0;
    let timer = null;
    let stopped = false;

    refresh();

    const connect = () => {
      socket = new WebSocket(liveSocketUrl());
      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
        refresh(); // catch up on anything missed while disconnected
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type !== 'ping') handleMessage(message).catch(() => {});
        } catch {
          /* ignore malformed message */
        }
      };
      socket.onclose = (event) => {
        setConnected(false);
        if (stopped) return;
        if (event.code === UNAUTHORIZED) {
          logout('Your session has expired. Please sign in again.');
          return;
        }
        const delay = RECONNECT_DELAYS_S[Math.min(attempt, RECONNECT_DELAYS_S.length - 1)];
        attempt += 1;
        timer = setTimeout(connect, delay * 1000);
      };
    };
    connect();

    return () => {
      stopped = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [session, refresh, handleMessage, logout]);

  // Polling fallback while the live connection is down
  useEffect(() => {
    if (!session || connected) return undefined;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [session, connected, refresh]);

  const subscribe = useCallback((listener) => {
    listeners.current.add(listener);
    return () => listeners.current.delete(listener);
  }, []);

  const value = {
    system,
    kit,
    reading,
    predictions,
    alertCount,
    connected,
    error,
    toasts,
    dismissToast,
    subscribe,
    refresh,
    tz: system?.site?.timezone ?? DEFAULT_TZ,
  };
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive() {
  return useContext(LiveContext);
}
