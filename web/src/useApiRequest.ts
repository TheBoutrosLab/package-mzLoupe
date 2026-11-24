import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "./api";

/** Callbacks belong to one request and run only while it is still current. */
interface ApiRequest<T> {
  url: string;
  options?: Omit<RequestInit, "signal">;
  onSuccess: (value: T) => void;
  onError?: (error: Error) => void;
}

/** Own one request lane: starting another request aborts and supersedes the first. */
export function useApiRequest() {
  const active = useRef<AbortController | undefined>(undefined);
  const mounted = useRef(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      active.current?.abort();
      active.current = undefined;
    };
  }, []);

  /** Cancel both network work and callbacks, including transports slow to abort. */
  const cancel = useCallback(() => {
    active.current?.abort();
    active.current = undefined;
    if (mounted.current) {
      setLoading(false);
      setError("");
    }
  }, []);

  /** Run success/error callbacks only for the latest mounted request. */
  const run = useCallback(async <T>(request: ApiRequest<T>): Promise<void> => {
    if (!mounted.current) return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setLoading(true);
    setError("");
    try {
      const value = await apiClient.request<T>(request.url, {
        ...request.options,
        signal: controller.signal
      });
      if (
        mounted.current &&
        active.current === controller &&
        !controller.signal.aborted
      ) {
        request.onSuccess(value);
      }
    } catch (failure) {
      if (
        mounted.current &&
        active.current === controller &&
        !controller.signal.aborted
      ) {
        const problem = failure instanceof Error ? failure : new Error(String(failure));
        setError(problem.message);
        request.onError?.(problem);
      }
    } finally {
      if (active.current === controller) {
        active.current = undefined;
        if (mounted.current) setLoading(false);
      }
    }
  }, []);

  const clearError = useCallback(() => setError(""), []);
  return { run, cancel, loading, error, clearError };
}
