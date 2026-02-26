import { useEffect, useRef, useCallback, useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

type EventHandler = (data: any) => void;

interface SSEConnection {
  eventSource: EventSource | null;
  handlers: Map<string, Set<EventHandler>>;
  connected: boolean;
}

// Singleton connection shared across all components
let globalConnection: SSEConnection = {
  eventSource: null,
  handlers: new Map(),
  connected: false,
};

let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let subscriberCount = 0;

function connect() {
  if (globalConnection.eventSource) return;
  
  try {
    const es = new EventSource(`${API_BASE}/api/events/stream`);
    globalConnection.eventSource = es;

    es.addEventListener('connected', () => {
      globalConnection.connected = true;
      console.log('[SSE] Connected');
    });

    es.addEventListener('ping', () => {
      // Keepalive — no action needed
    });

    // Listen for all known event types
    const eventTypes = [
      'chat:message',
      'smart_inbox:new',
      'smart_inbox:updated',
      'smart_inbox:stats',
      'reshop:new',
      'reshop:updated',
      'reshop:stats',
      'customers:updated',
      'sales:new',
      'sales:updated',
      'dashboard:refresh',
      'commission:updated',
    ];

    eventTypes.forEach((type) => {
      es.addEventListener(type, (event: MessageEvent) => {
        try {
          const parsed = JSON.parse(event.data);
          const handlers = globalConnection.handlers.get(type);
          if (handlers) {
            handlers.forEach((handler) => handler(parsed.data || parsed));
          }
          // Also fire wildcard handlers
          const wildcardHandlers = globalConnection.handlers.get('*');
          if (wildcardHandlers) {
            wildcardHandlers.forEach((handler) => handler({ type, ...parsed }));
          }
        } catch (e) {
          console.warn('[SSE] Parse error:', e);
        }
      });
    });

    es.onerror = () => {
      globalConnection.connected = false;
      globalConnection.eventSource = null;
      es.close();
      // Reconnect after 5s
      if (subscriberCount > 0 && !reconnectTimer) {
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connect();
        }, 5000);
      }
    };
  } catch (e) {
    console.warn('[SSE] Connection failed:', e);
  }
}

function disconnect() {
  if (globalConnection.eventSource) {
    globalConnection.eventSource.close();
    globalConnection.eventSource = null;
    globalConnection.connected = false;
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

/**
 * Subscribe to SSE events. Returns cleanup function.
 * 
 * Usage:
 *   useSSE('chat:message', (data) => { ... })
 *   useSSE('smart_inbox:new', (data) => { ... })
 *   useSSE('*', (data) => { ... })  // all events
 */
export function useSSE(eventType: string, handler: EventHandler) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const wrappedHandler: EventHandler = (data) => handlerRef.current(data);

    // Register handler
    if (!globalConnection.handlers.has(eventType)) {
      globalConnection.handlers.set(eventType, new Set());
    }
    globalConnection.handlers.get(eventType)!.add(wrappedHandler);
    subscriberCount++;

    // Ensure connected
    connect();

    return () => {
      globalConnection.handlers.get(eventType)?.delete(wrappedHandler);
      subscriberCount--;
      if (subscriberCount <= 0) {
        subscriberCount = 0;
        // Disconnect after a short delay (in case navigating between pages)
        setTimeout(() => {
          if (subscriberCount <= 0) disconnect();
        }, 2000);
      }
    };
  }, [eventType]);
}

/**
 * Hook that returns a refresh trigger — increments whenever the given event fires.
 * Use this to trigger data refetches.
 * 
 * Usage:
 *   const refreshKey = useSSERefresh('smart_inbox:new');
 *   useEffect(() => { fetchData(); }, [refreshKey]);
 */
export function useSSERefresh(...eventTypes: string[]): number {
  const [key, setKey] = useState(0);
  
  eventTypes.forEach((type) => {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useSSE(type, () => setKey((k) => k + 1));
  });

  return key;
}

/**
 * Hook for auto-polling with SSE boost.
 * Polls at `interval` ms, but also immediately refetches on SSE events.
 */
export function useLiveData<T>(
  fetchFn: () => Promise<T>,
  sseEvents: string[],
  intervalMs: number = 30000,
): { data: T | null; loading: boolean; error: string | null; refetch: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchRef = useRef(fetchFn);
  fetchRef.current = fetchFn;

  const doFetch = useCallback(async () => {
    try {
      const result = await fetchRef.current();
      setData(result);
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Fetch failed');
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch + interval
  useEffect(() => {
    doFetch();
    const timer = setInterval(doFetch, intervalMs);
    return () => clearInterval(timer);
  }, [doFetch, intervalMs]);

  // SSE-triggered refetch
  sseEvents.forEach((type) => {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useSSE(type, () => doFetch());
  });

  return { data, loading, error, refetch: doFetch };
}
