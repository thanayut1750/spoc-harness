import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { activityMatches, mergeActivity } from "./activityHistory";
import type {
  ActivityEvent,
  ActivityScope,
  ActivitySubscription,
} from "./types";

interface HistoryState {
  key: string;
  events: ActivityEvent[];
  nextBefore: number | null;
  hasMore: boolean;
  loading: boolean;
  error: string;
}

export function useActivityHistory({
  scope,
  liveEvents,
  snapshot,
  enabled = true,
  resetVersion = 0,
  onReset,
  subscribe,
}: {
  scope: ActivityScope;
  liveEvents: ActivityEvent[];
  snapshot: { generation?: string } | null;
  enabled?: boolean;
  resetVersion?: number;
  onReset: () => void;
  subscribe: ActivitySubscription;
}) {
  const { run_id, source, agent_id } = scope;
  const generation = snapshot?.generation;
  const ready = snapshot !== null;
  const key = JSON.stringify([
    run_id,
    source,
    agent_id,
    generation,
    resetVersion,
  ]);
  const currentKey = useRef(key);
  currentKey.current = key;
  const resetCallback = useRef(onReset);
  resetCallback.current = onReset;
  const [state, setState] = useState<HistoryState>({
    key: "",
    events: [],
    nextBefore: null,
    hasMore: false,
    loading: false,
    error: "",
  });
  const requestVersion = useRef(0);
  const load = useCallback(
    async (before?: number) => {
      if (!ready || !enabled) return;
      const version = ++requestVersion.current;
      setState((current) => ({ ...current, loading: true, error: "" }));
      try {
        const page = await api.history(
          { run_id, source, agent_id },
          before,
          generation,
        );
        if (version !== requestVersion.current || currentKey.current !== key)
          return;
        if (
          page.reset ||
          (generation && page.generation && generation !== page.generation)
        ) {
          setState({
            key,
            events: [],
            nextBefore: null,
            hasMore: false,
            loading: false,
            error: "",
          });
          resetCallback.current();
          return;
        }
        setState((current) => ({
          key,
          events: mergeActivity(
            current.key === key ? current.events : [],
            page.events,
            { run_id, source, agent_id },
          ),
          nextBefore: page.next_before,
          hasMore: page.has_more,
          loading: false,
          error: "",
        }));
      } catch (failure) {
        if (version !== requestVersion.current || currentKey.current !== key)
          return;
        setState((current) => ({
          ...current,
          loading: false,
          error: `Could not load activity: ${failure instanceof Error ? failure.message : "The request failed."}`,
        }));
      }
    },
    [ready, enabled, run_id, source, agent_id, generation, key],
  );
  useEffect(() => {
    setState({
      key,
      events: [],
      nextBefore: null,
      hasMore: false,
      loading: enabled,
      error: "",
    });
    void load();
    return () => {
      requestVersion.current += 1;
    };
  }, [key, load, enabled]);
  useEffect(() => {
    if (!enabled) return;
    setState((current) =>
      current.key === key
        ? {
            ...current,
            events: mergeActivity(current.events, liveEvents, {
              run_id,
              source,
              agent_id,
            }),
          }
        : current,
    );
  }, [liveEvents, key, enabled, run_id, source, agent_id]);
  // Subscribe before the 200-event animation buffer can evict a batched burst.
  useEffect(() => {
    if (!enabled) return;
    const scope = { run_id, source, agent_id };
    return subscribe((event) => {
      if (currentKey.current !== key || !activityMatches(event, scope)) return;
      setState((current) =>
        current.key === key
          ? {
              ...current,
              events: mergeActivity(current.events, [event], scope),
            }
          : current,
      );
    });
  }, [subscribe, key, enabled, run_id, source, agent_id]);
  const current = state.key === key ? state : null;
  return {
    events: mergeActivity(current?.events ?? [], liveEvents, scope),
    loading: current?.loading ?? enabled,
    error: current?.error ?? "",
    hasMore: current?.hasMore ?? false,
    loadEarlier: () => void load(current?.nextBefore ?? undefined),
    retry: () => void load(current?.nextBefore ?? undefined),
  };
}
