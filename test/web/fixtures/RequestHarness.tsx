import React, { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { apiClient } from "../../../web/src/api";
import { useApiRequest } from "../../../web/src/useApiRequest";

interface Reply {
  name: string;
}
interface ControlledRequest {
  url: string;
  signal: AbortSignal;
  resolve: (value: Reply) => void;
  reject: (error: Error) => void;
}

declare global {
  interface Window {
    requests: ControlledRequest[];
    successes: string[];
  }
}

window.requests = [];
window.successes = [];
// Deliberately ignore abort so the hook must also suppress obsolete callbacks.
apiClient.request = <T,>(url: string, options?: RequestInit): Promise<T> => {
  if (!options?.signal) throw new Error("A request must carry its cancellation signal.");
  const signal = options.signal;
  return new Promise<T>((resolve, reject) => {
    window.requests.push({
      url,
      signal,
      resolve: (value) => resolve(value as T),
      reject
    });
  });
};

/** Exercise an effect-driven read and its cleanup under React StrictMode. */
function Probe({ path }: { path: string }) {
  const { run, cancel, loading, error } = useApiRequest();
  const [result, setResult] = useState("");
  useEffect(() => {
    run<Reply>({
      url: path,
      onSuccess: (reply) => {
        window.successes.push(reply.name);
        setResult(reply.name);
      }
    });
    return cancel;
  }, [path, run, cancel]);
  return (
    <div>
      <output data-testid="result">{result}</output>
      <output data-testid="loading">{String(loading)}</output>
      <output data-testid="error">{error}</output>
    </div>
  );
}

/** Let the browser test change request context and mount/unmount the consumer. */
function Harness() {
  const [path, setPath] = useState("first");
  const [visible, setVisible] = useState(true);
  return (
    <div>
      {["second", "third", "fourth", "fifth"].map((name) => (
        <button
          key={name}
          onClick={() => setPath(name)}
        >
          {name}
        </button>
      ))}
      <button onClick={() => setVisible(!visible)}>Toggle consumer</button>
      {visible && <Probe path={path} />}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Harness />
  </StrictMode>
);
