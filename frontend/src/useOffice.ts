import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  appendEvent,
  initialAgents,
  normalizeAgent,
  parseActivityEvent,
  projectEvent,
} from "./office";
import type { ActivityEvent, AgentActivity } from "./types";
export function useOffice(onEvent: (event: ActivityEvent) => void) {
  const [agents, setAgents] =
    useState<Record<string, AgentActivity>>(initialAgents);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connection, setConnection] = useState<
    "connecting" | "live" | "offline"
  >("connecting");
  const [error, setError] = useState("");
  const cursor = useRef(0);
  const eventCallback = useRef(onEvent);
  useEffect(() => {
    eventCallback.current = onEvent;
  }, [onEvent]);
  const receive = useCallback((event: MessageEvent<string>) => {
    const raw = parseActivityEvent(event.data);
    const parsed = raw ? normalizeAgent(raw) : null;
    if (!parsed || parsed.seq <= cursor.current) return;
    cursor.current = parsed.seq;
    setAgents((current) => projectEvent(current, parsed));
    setEvents((current) => appendEvent(current, parsed));
    eventCallback.current(parsed);
  }, []);
  useEffect(() => {
    let disposed = false;
    let stream: EventSource | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    async function connect(snapshot = false) {
      try {
        if (snapshot) {
          const state = await api.office();
          if (disposed) return;
          cursor.current = state.cursor;
          setAgents({
            ...initialAgents(),
            ...Object.fromEntries(
              state.agents.map((raw) => {
                const agent = normalizeAgent(raw);
                return [agent.agent_id, agent];
              }),
            ),
          });
        }
        if (disposed) return;
        stream = new EventSource(`/api/events?after=${cursor.current}`);
        stream.onopen = () => {
          if (!disposed) {
            setConnection("live");
            setError("");
          }
        };
        stream.onmessage = receive;
        stream.addEventListener("activity", receive as EventListener);
        stream.onerror = () => {
          stream?.close();
          if (!disposed) {
            setConnection("offline");
            setError("Reconnecting to the office…");
            retry = setTimeout(() => void connect(), 2500);
          }
        };
      } catch (failure) {
        if (!disposed) {
          setConnection("offline");
          setError(
            failure instanceof Error ? failure.message : "Office unavailable",
          );
          retry = setTimeout(() => void connect(true), 3000);
        }
      }
    }
    void connect(true);
    return () => {
      disposed = true;
      stream?.close();
      clearTimeout(retry);
    };
  }, [receive]);
  return { agents, events, connection, error };
}
