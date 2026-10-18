import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  appendEvent,
  activityLabels,
  initialAgents,
  normalizeAgent,
  parseActivityEvent,
  projectEvent,
} from "./office";
import type { ActivityEvent, AgentActivity } from "./types";
export function useOffice(
  onEvent: (event: ActivityEvent) => void,
  resetVersion = 0,
  onReset?: () => void,
) {
  const [agents, setAgents] =
    useState<Record<string, AgentActivity>>(initialAgents);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connection, setConnection] = useState<
    "connecting" | "live" | "offline"
  >("connecting");
  const [error, setError] = useState("");
  const cursor = useRef(0);
  const generation = useRef<string | undefined>(undefined);
  const eventCallback = useRef(onEvent);
  const resetCallback = useRef(onReset);
  useEffect(() => {
    resetCallback.current = onReset;
  }, [onReset]);
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
    cursor.current = 0;
    generation.current = undefined;
    setAgents(initialAgents());
    setEvents([]);
    setConnection("connecting");
    setError("");
    let stream: EventSource | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let hasSnapshot = false;
    async function connect() {
      try {
        const state = await api.office();
        if (disposed) return;
        if (
          !Array.isArray(state?.agents) ||
          !Number.isSafeInteger(state.cursor) ||
          state.cursor < 0
        )
          throw new Error("The harness returned an invalid office snapshot.");
        const snapshotAgents = state.agents.map((raw) => {
          if (
            !raw ||
            typeof raw.agent_id !== "string" ||
            !Object.hasOwn(activityLabels, raw.activity)
          )
            throw new Error("The harness returned an invalid agent activity.");
          return normalizeAgent(raw);
        });
        const changed =
          hasSnapshot &&
          ((generation.current !== undefined &&
            state.generation !== undefined &&
            generation.current !== state.generation) ||
            ((generation.current === undefined ||
              state.generation === undefined) &&
              state.cursor < cursor.current));
        generation.current = state.generation;
        // A reconnect snapshot updates the desks; SSE still replays missed history.
        if (!hasSnapshot || changed) cursor.current = state.cursor;
        hasSnapshot = true;
        if (changed) {
          setEvents([]);
          if (resetCallback.current) {
            resetCallback.current();
            return;
          }
        }
        setAgents((current) => ({
          ...initialAgents(),
          ...Object.fromEntries(
            snapshotAgents.map((agent) => {
              const newer = !changed && current[agent.agent_id];
              return [
                agent.agent_id,
                newer && (newer.seq ?? -1) > (agent.seq ?? -1) ? newer : agent,
              ];
            }),
          ),
        }));
        const query = new URLSearchParams({ after: String(cursor.current) });
        if (generation.current) query.set("generation", generation.current);
        stream = new EventSource(`/api/events?${query}`);
        stream.onopen = () => {
          if (!disposed) {
            setConnection("live");
            setError("");
          }
        };
        const receiveCurrent = (event: MessageEvent<string>) => {
          if (!disposed) receive(event);
        };
        stream.onmessage = receiveCurrent;
        stream.addEventListener("activity", receiveCurrent as EventListener);
        stream.addEventListener("reset", () => {
          if (disposed) return;
          stream?.close();
          clearTimeout(retry);
          cursor.current = 0;
          generation.current = undefined;
          hasSnapshot = false;
          setAgents(initialAgents());
          setEvents([]);
          setConnection("connecting");
          if (resetCallback.current) resetCallback.current();
          else void connect();
        });
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
          retry = setTimeout(() => void connect(), 3000);
        }
      }
    }
    void connect();
    return () => {
      disposed = true;
      stream?.close();
      clearTimeout(retry);
    };
  }, [receive, resetVersion]);
  return { agents, events, connection, error };
}
