import { useEffect, useRef, useState, useCallback } from 'react';
import type { Signal, WSMessage } from '../types';

interface UseWebSocketOptions {
  onSignal?: (signal: Signal) => void;
  onHealth?: (health: Record<string, boolean>) => void;
  onPlugStatus?: (status: Record<string, unknown>) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  autoReconnect?: boolean;
  reconnectInterval?: number;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  sendMessage: (message: unknown) => void;
  lastMessage: WSMessage | null;
}

export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketReturn {
  const {
    onSignal,
    onHealth,
    onPlugStatus,
    onConnect,
    onDisconnect,
    autoReconnect = true,
    reconnectInterval = 3000,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setIsConnected(true);
      onConnect?.();
    };

    ws.onclose = () => {
      setIsConnected(false);
      wsRef.current = null;
      onDisconnect?.();

      if (autoReconnect) {
        reconnectTimeoutRef.current = window.setTimeout(() => {
          connect();
        }, reconnectInterval);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data);
        setLastMessage(message);

        switch (message.type) {
          case 'signal':
            onSignal?.(message.data as Signal);
            break;
          case 'health':
            onHealth?.(message.data as Record<string, boolean>);
            break;
          case 'plug_status':
            onPlugStatus?.(message.data as Record<string, unknown>);
            break;
          case 'ping':
            // Respond to ping
            ws.send(JSON.stringify({ type: 'pong' }));
            break;
        }
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };

    wsRef.current = ws;
  }, [onSignal, onHealth, onPlugStatus, onConnect, onDisconnect, autoReconnect, reconnectInterval]);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  const sendMessage = useCallback((message: unknown) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  return { isConnected, sendMessage, lastMessage };
}

export default useWebSocket;
