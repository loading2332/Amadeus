const SESSION_STORAGE = "amadeus_session";

const state = {
  userId: null,
  sessionId: null,
  busy: true,
};

const nodes = {
  messages: document.querySelector("#messages"),
  composer: document.querySelector("#composer"),
  input: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  sessionLabel: document.querySelector("#sessionLabel"),
  statusBadge: document.querySelector("#statusBadge"),
};

function readStoredSession(ownerUserId) {
  const raw = window.localStorage.getItem(SESSION_STORAGE);
  if (!raw) {
    return null;
  }
  try {
    const value = JSON.parse(raw);
    const userId = Number.parseInt(value.user_id, 10);
    const sessionId = Number.parseInt(value.session_id, 10);
    if (
      userId === ownerUserId
      && Number.isInteger(sessionId)
      && sessionId > 0
    ) {
      return {
        user_id: userId,
        session_id: sessionId,
      };
    }
  } catch {
    // Fall through to create a fresh server-owned session.
  }
  window.localStorage.removeItem(SESSION_STORAGE);
  return null;
}

async function getBootstrap() {
  const response = await fetch("/api/bootstrap");
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const payload = await response.json();
  const ownerUserId = Number.parseInt(payload.owner_user_id, 10);
  if (!Number.isInteger(ownerUserId) || ownerUserId <= 0) {
    throw new Error("Invalid owner bootstrap");
  }
  return ownerUserId;
}

async function getOrCreateSession() {
  const existing = readStoredSession(state.userId);
  if (existing) {
    return existing;
  }
  const response = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: "Web chat",
      metadata: { channel: "web" },
    }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const created = await response.json();
  window.localStorage.setItem(
    SESSION_STORAGE,
    JSON.stringify({
      user_id: created.user_id,
      session_id: created.session_id,
    }),
  );
  return created;
}

function applySession(session) {
  state.userId = session.user_id;
  state.sessionId = session.session_id;
  nodes.sessionLabel.textContent = `user ${state.userId} / session ${state.sessionId}`;
}

function setStatus(status) {
  nodes.statusBadge.textContent = status;
}

function setBusy(value, status = value ? "pending" : "idle") {
  state.busy = value;
  nodes.input.disabled = value;
  nodes.sendButton.disabled = value;
  setStatus(status);
}

function appendMessage(role, content) {
  nodes.messages.querySelector(".empty")?.remove();
  const item = document.createElement("article");
  item.className = `message ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;
  item.append(bubble);
  nodes.messages.append(item);
  nodes.messages.scrollTop = nodes.messages.scrollHeight;
}

async function sendMessage(message) {
  if (state.sessionId === null) {
    throw new Error("Session is not ready");
  }
  appendMessage("user", message);
  setBusy(true, "pending");
  let response = await createTurn(message);
  if (!response.ok) {
    window.localStorage.removeItem(SESSION_STORAGE);
    const session = await getOrCreateSession();
    applySession(session);
    response = await createTurn(message);
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const payload = await response.json();
  await waitForTurn(payload.turn_id);
}

async function createTurn(message) {
  const response = await fetch("/api/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: state.sessionId,
    }),
  });
  return response;
}

async function waitForTurn(turnId) {
  if ("EventSource" in window) {
    try {
      await waitForSse(turnId);
      return;
    } catch {
      setStatus("polling");
    }
  }
  await pollTurn(turnId);
}

function waitForSse(turnId) {
  return new Promise((resolve, reject) => {
    const source = new EventSource(`/api/turns/${turnId}/events`);
    const timeout = window.setTimeout(() => {
      source.close();
      reject(new Error("SSE timeout"));
    }, 120000);

    const onEvent = (event) => {
      const data = JSON.parse(event.data);
      setStatus(data.status);
      if (data.status === "done") {
        window.clearTimeout(timeout);
        source.close();
        appendMessage("assistant", data.answer || "");
        resolve();
      }
      if (data.status === "failed") {
        window.clearTimeout(timeout);
        source.close();
        reject(new Error(data.error || "turn failed"));
      }
    };

    for (const status of ["pending", "processing", "done", "failed"]) {
      source.addEventListener(status, onEvent);
    }
    source.onerror = () => {
      window.clearTimeout(timeout);
      source.close();
      reject(new Error("SSE disconnected"));
    };
  });
}

async function pollTurn(turnId) {
  for (;;) {
    const response = await fetch(`/api/turns/${turnId}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    setStatus(data.status);
    if (data.status === "done") {
      appendMessage("assistant", data.answer || "");
      return;
    }
    if (data.status === "failed") {
      throw new Error(data.error || "turn failed");
    }
    await new Promise((resolve) => window.setTimeout(resolve, 750));
  }
}

nodes.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = nodes.input.value.trim();
  if (!message || state.busy) {
    return;
  }
  nodes.input.value = "";
  nodes.input.style.height = "auto";
  try {
    await sendMessage(message);
  } catch (error) {
    appendMessage("assistant", "请求失败，请检查 worker 或稍后重试。");
    setStatus(error instanceof Error ? error.message : "failed");
  } finally {
    setBusy(false);
    nodes.input.focus();
  }
});

nodes.input.addEventListener("input", () => {
  nodes.input.style.height = "auto";
  nodes.input.style.height = `${Math.min(nodes.input.scrollHeight, 160)}px`;
});

nodes.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    nodes.composer.requestSubmit();
  }
});

nodes.messages.innerHTML = '<div class="empty">开始对话</div>';
setBusy(true, "initializing");
getBootstrap()
  .then((ownerUserId) => {
    state.userId = ownerUserId;
    return getOrCreateSession();
  })
  .then((session) => {
    applySession(session);
    setBusy(false);
    nodes.input.focus();
  })
  .catch((error) => {
    setStatus(error instanceof Error ? error.message : "session failed");
  });
