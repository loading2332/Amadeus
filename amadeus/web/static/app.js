const state = {
  sessionKey: getOrCreateSessionKey(),
  busy: false,
};

const nodes = {
  messages: document.querySelector("#messages"),
  composer: document.querySelector("#composer"),
  input: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  sessionLabel: document.querySelector("#sessionLabel"),
  statusBadge: document.querySelector("#statusBadge"),
};

function getOrCreateSessionKey() {
  const existing = window.localStorage.getItem("amadeus_session_key");
  if (existing) {
    return existing;
  }
  const created = `web:${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
  window.localStorage.setItem("amadeus_session_key", created);
  return created;
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
  appendMessage("user", message);
  setBusy(true, "pending");
  const response = await fetch("/api/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_key: state.sessionKey,
    }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const payload = await response.json();
  await waitForTurn(payload.turn_id);
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

nodes.sessionLabel.textContent = state.sessionKey;
nodes.messages.innerHTML = '<div class="empty">开始对话</div>';
