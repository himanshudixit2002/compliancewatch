// Talking to the control app's local helper (panel_server.py): the token, JSON requests, the
// event stream and the heartbeat.
//
// No token ever travels in a URL. The address the window opens carries a launch code instead
// (http://127.0.0.1:<port>/#launch=...): single use, valid 30 seconds, worth nothing once
// swapped. The page removes it from the address bar at once, swaps it for the token with
// POST /api/launch, keeps the token in this module's memory only (never in storage), and sends
// it as X-Panel-Token on every request, the event stream included: the stream is read with
// fetch(), not EventSource, so it can carry the header like everything else.

const TOKEN_HEADER = "X-Panel-Token";
let token = "";

/**
 * Takes the launch code from the address (and removes it from the address bar before anything
 * else), then swaps it for the token. True when the window has its token.
 */
export async function takeLaunch() {
  const hash = window.location.hash.replace(/^#/, "");
  const params = new URLSearchParams(hash.includes("=") ? hash : "");
  const code = params.get("launch");
  if (params.has("launch") || params.has("token")) {
    const view = params.get("view");
    const rest = view ? `#/${view.replace(/^\/+/, "")}` : "#/home";
    window.history.replaceState(null, "", `${window.location.pathname}${rest}`);
  }
  if (!code || token) return token !== "";
  try {
    const response = await fetch("/api/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ code }),
      cache: "no-store",
      credentials: "omit",
    });
    if (!response.ok) return false;
    const data = await response.json();
    if (typeof data.token === "string" && data.token) token = data.token;
  } catch {
    return false;
  }
  return token !== "";
}

export function hasToken() {
  return token !== "";
}

/** A failed request, in the words the window shows. */
export class ApiError extends Error {
  constructor({ status = 0, code = "", title = "", detail = "", fix = "", action = "" } = {}) {
    super(title || detail || `request failed (${status})`);
    this.status = status;
    this.code = code;
    this.title = title;
    this.detail = detail;
    this.fix = fix;
    this.action = action;
  }
}

function headers(extra = {}) {
  return { [TOKEN_HEADER]: token, Accept: "application/json", ...extra };
}

/** One JSON request. Throws ApiError with the server's own words when it gives them. */
export async function request(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: headers(body === undefined ? {} : { "Content-Type": "application/json" }),
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      credentials: "omit",
    });
  } catch (error) {
    throw new ApiError({ code: "offline", detail: String(error?.message ?? error) });
  }
  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text.slice(0, 2000) };
    }
  }
  if (!response.ok) {
    const problem = data?.error ?? data ?? {};
    throw new ApiError({
      status: response.status,
      code: problem.code ?? problem.type ?? (response.status === 401 ? "unauthorized" : ""),
      title: problem.message ?? problem.title ?? "",
      detail: problem.detail ?? "",
      fix: problem.fix ?? "",
      action: problem.action ?? problem.action_id ?? "",
    });
  }
  return data ?? {};
}

const get = (path) => request("GET", path);
const post = (path, body = {}) => request("POST", path, body);
const enc = encodeURIComponent;

export const api = {
  status: () => get("/api/status"),
  actions: () => get("/api/actions"),
  // A run of anything but a safe action carries the token its preview gave (API.md, 4).
  run: (id, params = {}, confirmToken = null) =>
    post(
      `/api/actions/${enc(id)}/run`,
      confirmToken ? { params, confirm_token: confirmToken } : { params },
    ),
  preview: (id, params = {}) => post(`/api/actions/${enc(id)}/preview`, { params }),
  cancel: (runId) => post(`/api/runs/${enc(runId)}/cancel`),
  runs: (limit = 30) => get(`/api/runs?limit=${limit}`),
  runDetail: (runId) => get(`/api/runs/${enc(runId)}`),
  features: () => get("/api/features"),
  flags: () => get("/api/flags"),
  processes: () => get("/api/processes"),
  stopPreview: (pid) => get(`/api/processes/${enc(pid)}/stop-preview`),
  stopProcess: (pid, mode, confirmToken) =>
    post(`/api/processes/${enc(pid)}/stop`, { mode, confirm_token: confirmToken }),
  logSources: () => get("/api/logs"),
  log: (id, tail = 500) => get(`/api/logs/${enc(id)}?tail=${tail}`),
  kafka: () => get("/api/kafka"),
  kafkaRefresh: () => post("/api/kafka/refresh"),
  docs: () => get("/api/docs"),
  openDoc: (id) => post(`/api/docs/${enc(id)}/open`),
  github: () => get("/api/github"),
  heartbeat: () => post("/api/heartbeat"),
  quit: () => post("/api/quit"),
  prefs: () => get("/api/prefs"),
  savePrefs: (prefs) => request("PUT", "/api/prefs", prefs),
};

/**
 * Reads the server-sent events of /api/events and calls onEvent(type, data) for each one.
 * Reconnects by itself (1, 2, 4, then 10 s apart) and reports the connection through
 * onState("live" | "reconnecting" | "offline" | "unauthorized"). A stream that sends nothing,
 * not even its ping comment, for 45 s is taken as stalled and opened again.
 */
export function connectEvents({ onEvent, onState, onOpen }) {
  let stopped = false;
  let paused = false;
  let looping = false;
  let controller = null;
  let lastId = "";
  let failures = 0;
  let watchdog = 0;

  const resetWatchdog = () => {
    window.clearTimeout(watchdog);
    watchdog = window.setTimeout(() => controller?.abort(), 45000);
  };

  async function readOnce() {
    controller = new AbortController();
    const extra = { Accept: "text/event-stream" };
    if (lastId) extra["Last-Event-ID"] = lastId;
    const response = await fetch("/api/events", {
      headers: headers(extra),
      signal: controller.signal,
      cache: "no-store",
      credentials: "omit",
    });
    if (response.status === 401 || response.status === 403) {
      throw new ApiError({ status: response.status, code: "unauthorized" });
    }
    if (!response.ok || !response.body) {
      throw new ApiError({ status: response.status, code: "stream" });
    }
    failures = 0;
    onState("live");
    onOpen?.();
    resetWatchdog();
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let type = "";
    let data = [];
    const dispatch = () => {
      if (data.length) {
        const text = data.join("\n");
        let parsed = text;
        try {
          parsed = JSON.parse(text);
        } catch {
          // a plain-text event keeps its text
        }
        onEvent(type || "message", parsed);
      }
      type = "";
      data = [];
    };
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      resetWatchdog();
      buffer += decoder.decode(value, { stream: true });
      let index;
      while ((index = buffer.search(/\r\n|\r|\n/)) >= 0) {
        if (buffer[index] === "\r" && index === buffer.length - 1) break; // wait for a following \n
        const line = buffer.slice(0, index);
        buffer = buffer.slice(index + (buffer.startsWith("\r\n", index) ? 2 : 1));
        if (line === "") {
          dispatch();
          continue;
        }
        if (line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        let content = colon === -1 ? "" : line.slice(colon + 1);
        if (content.startsWith(" ")) content = content.slice(1);
        if (field === "event") type = content;
        else if (field === "data") data.push(content);
        else if (field === "id") lastId = content;
      }
    }
  }

  async function loop() {
    looping = true;
    try {
      while (!stopped && !paused) {
        try {
          await readOnce();
          if (stopped || paused) return;
          failures += 1;
        } catch (error) {
          if (stopped || paused) return;
          if (error instanceof ApiError && error.code === "unauthorized") {
            onState("unauthorized");
            return;
          }
          failures += 1;
        } finally {
          window.clearTimeout(watchdog);
        }
        onState(failures >= 4 ? "offline" : "reconnecting");
        const wait = [1000, 2000, 4000][failures - 1] ?? 10000;
        await new Promise((resolve) => window.setTimeout(resolve, wait));
      }
    } finally {
      looping = false;
    }
  }

  loop();
  return {
    /** Ends the stream for good (the page is going away). */
    close() {
      stopped = true;
      window.clearTimeout(watchdog);
      controller?.abort();
    },
    /** Lets go of the stream while the window is hidden; ``resume`` picks it up again. */
    pause() {
      if (stopped || paused) return;
      paused = true;
      window.clearTimeout(watchdog);
      controller?.abort();
    },
    /** Reads the stream again, from the last event it saw (the helper replays what it missed). */
    resume() {
      if (stopped || !paused) return;
      paused = false;
      failures = 0;
      if (!looping) loop();
    },
    reconnect() {
      controller?.abort();
    },
  };
}

/** Tells the helper the window is still open (it exits after ten minutes without one). */
export function startHeartbeat(onResult) {
  const beat = () =>
    api.heartbeat().then(
      () => onResult?.(true),
      (error) => onResult?.(false, error),
    );
  beat();
  const timer = window.setInterval(beat, 20000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") beat();
  });
  return () => window.clearInterval(timer);
}
