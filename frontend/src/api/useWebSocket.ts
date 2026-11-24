import { useEffect, useRef, useState, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, IS_MOCK_ENV } from './client';
import { Event } from './types';

interface WebSocketHookResult {
  status: 'connected' | 'connecting' | 'disconnected';
  lastSeq: number;
  liveEvents: Event[];
  staleAlert: { message: string; count: number } | null;
  clearStaleAlert: () => void;
}

export function useRoomWebSocket(roomId: string | null): WebSocketHookResult {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<'connected' | 'connecting' | 'disconnected'>('disconnected');
  const [lastSeq, setLastSeq] = useState<number>(0);
  const [liveEvents, setLiveEvents] = useState<Event[]>([]);
  const [staleAlert, setStaleAlert] = useState<{ message: string; count: number } | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const pingIntervalRef = useRef<any>(null);
  const reconnectTimeoutRef = useRef<any>(null);
  const lastSeqRef = useRef<number>(0);
  lastSeqRef.current = lastSeq;

  const handleIncomingEvent = useCallback(
    (event: Event) => {
      if (event.seq) {
        setLastSeq(event.seq);
      }
      setLiveEvents((prev) => [event, ...prev.slice(0, 99)]);

      // Check for decision change / record stale to show banner
      if (event.type === 'decision.changed') {
        const count = event.payload?.stale_count ?? 1;
        const note = event.payload?.note ? ` (${event.payload.note})` : '';
        setStaleAlert({
          message: `${event.summary || 'A decision changed'}${note}: ${count} output(s) now stale`,
          count,
        });
      } else if (event.type === 'record.stale') {
        const reason = event.payload?.reason || 'Dependent decision changed';
        setStaleAlert((prev) => ({
          message: prev?.message || `Work marked stale: ${reason}`,
          count: (prev?.count ?? 0) + 1,
        }));
      }

      // Invalidate relevant queries
      if (roomId) {
        queryClient.invalidateQueries({ queryKey: ['board', roomId] });
        queryClient.invalidateQueries({ queryKey: ['events', roomId] });
        queryClient.invalidateQueries({ queryKey: ['records', roomId] });
        queryClient.invalidateQueries({ queryKey: ['submissions', roomId] });
        queryClient.invalidateQueries({ queryKey: ['approvals', roomId] });
        queryClient.invalidateQueries({ queryKey: ['recovery', roomId] });
        queryClient.invalidateQueries({ queryKey: ['presence', roomId] });
        queryClient.invalidateQueries({ queryKey: ['members', roomId] });
        queryClient.invalidateQueries({ queryKey: ['agents', roomId] });
        queryClient.invalidateQueries({ queryKey: ['room', roomId] });
        queryClient.invalidateQueries({ queryKey: ['rooms'] });
      }
    },
    [roomId, queryClient]
  );

  useEffect(() => {
    if (!roomId) {
      setStatus('disconnected');
      return;
    }

    const token = api.getToken();
    const isMock = api.getIsMockMode();

    if (isMock) {
      setStatus('connected');
      // Mock periodic activity
      const mockInterval = setInterval(() => {
        // Occasional mock ping
      }, 5000);
      return () => clearInterval(mockInterval);
    }

    const rawBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    const wsBaseUrl = rawBaseUrl.replace(/^http/, 'ws');
    const wsUrl = `${wsBaseUrl}/ws/rooms/${roomId}?token=${encodeURIComponent(
      token || ''
    )}${lastSeqRef.current ? `&since_seq=${lastSeqRef.current}` : ''}`;

    let isDisposed = false;

    function connect() {
      if (isDisposed) return;
      setStatus('connecting');

      try {
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (isDisposed) {
            ws.close();
            return;
          }
          setStatus('connected');
          // Start ping interval every 25s
          pingIntervalRef.current = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ kind: 'ping' }));
            }
          }, 25000);
        };

        ws.onmessage = (msgEvt) => {
          try {
            const data = JSON.parse(msgEvt.data);
            if (data.kind === 'hello') {
              if (data.latest_seq) {
                setLastSeq(data.latest_seq);
              }
              if (data.presence) {
                queryClient.setQueryData(['presence', roomId], data.presence);
              }
            } else if (data.kind === 'event' && data.event) {
              handleIncomingEvent(data.event);
            }
          } catch (e) {
            console.error('Error parsing WS message:', e);
          }
        };

        ws.onclose = (closeEvt) => {
          clearInterval(pingIntervalRef.current);
          if (isDisposed) return;
          setStatus('disconnected');

          // If close was 4401 (unauthorized), don't loop endlessly
          if (closeEvt.code === 4401) {
            console.warn('WS unauthorized');
            return;
          }

          // Auto-reconnect after 2 seconds
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, 2000);
        };

        ws.onerror = (err) => {
          console.warn('WS error, closing:', err);
          ws.close();
        };
      } catch (err) {
        setStatus('disconnected');
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, 3000);
      }
    }

    connect();

    return () => {
      isDisposed = true;
      clearInterval(pingIntervalRef.current);
      clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [roomId, handleIncomingEvent, queryClient]);

  const clearStaleAlert = useCallback(() => {
    setStaleAlert(null);
  }, []);

  return {
    status,
    lastSeq,
    liveEvents,
    staleAlert,
    clearStaleAlert,
  };
}
