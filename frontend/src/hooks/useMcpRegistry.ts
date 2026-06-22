import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ConnectServerRequest, ServerView, ToolDescriptor } from "../types/mcp";

export function useMcpRegistry() {
  const [servers, setServers] = useState<ServerView[]>([]);
  const [tools, setTools] = useState<ToolDescriptor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextServers, nextTools] = await Promise.all([api.servers(), api.tools()]);
      setServers(nextServers);
      setTools(nextTools);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Registry refresh failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const connect = useCallback(
    async (request: ConnectServerRequest) => {
      await api.connect(request);
      await refresh();
    },
    [refresh],
  );

  const disconnect = useCallback(
    async (serverId: string) => {
      await api.disconnect(serverId);
      await refresh();
    },
    [refresh],
  );

  return { servers, tools, loading, error, refresh, connect, disconnect };
}

