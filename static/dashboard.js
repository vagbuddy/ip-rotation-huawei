const ACTIONS = [
  { id: "status", title: "status", hint: "GET /status", input: "не требуется", endpoint: "/status", placeholder: "Здесь появится JSON-ответ" },
  { id: "public-ip", title: "public-ip", hint: "GET /public-ip", input: "не требуется", endpoint: "/public-ip", placeholder: "Здесь появится внешний IP" },
  { id: "rotate", title: "rotate ip", hint: "GET /rotate", input: "асинхронно", endpoint: "/rotate", placeholder: "Ответ запуска: rotating. Финал смотри в /status" },
  { id: "mode-3g", title: "set-mode 3g", hint: "GET /mode/3g", input: "3g", endpoint: "/mode/3g", placeholder: "Ответ после переключения режима" },
  { id: "mode-4g", title: "set-mode 4g", hint: "GET /mode/4g", input: "4g", endpoint: "/mode/4g", placeholder: "Ответ после переключения режима" },
  { id: "mobile-on", title: "mobile-data on", hint: "GET /mobile-data/on", input: "1", endpoint: "/mobile-data/on", placeholder: "Ответ после включения mobile data" },
  { id: "mobile-off", title: "mobile-data off", hint: "GET /mobile-data/off", input: "0", endpoint: "/mobile-data/off", placeholder: "Ответ после выключения mobile data" },
  { id: "reconnect", title: "reconnect", hint: "GET /reconnect", input: "не требуется", endpoint: "/reconnect", placeholder: "Ответ после переподключения" },
  { id: "reboot", title: "reboot (modern)", hint: "GET /reboot", input: "ControlModeEnum.REBOOT", endpoint: "/reboot", placeholder: "Ответ после отправки команды reboot" },
];

const ROTATE_LOG_ENDPOINT = "/rotate-log";
const ROTATE_LOG_POLL_INTERVAL_MS = 3000;

let rotateLogSignature = "";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderRows() {
  const rowsContainer = document.getElementById("rows");
  rowsContainer.innerHTML = ACTIONS.map((action) => `
    <div class="action-row">
      <div class="title">
        <strong>${escapeHtml(action.title)}</strong>
        <span>${escapeHtml(action.hint)}</span>
      </div>
      <div><input class="input" id="${escapeHtml(action.id)}-input" value="${escapeHtml(action.input)}" readonly></div>
      <div><button class="button" type="button" onclick="runAction('${escapeHtml(action.endpoint)}', '${escapeHtml(action.id)}-result', this)">Выполнить</button></div>
      <div><textarea class="result" id="${escapeHtml(action.id)}-result" readonly placeholder="${escapeHtml(action.placeholder)}"></textarea></div>
    </div>
  `).join("");
}

function formatResponse(text) {
  const trimmed = text.trim();
  if (!trimmed) {
    return "<empty response>";
  }

  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch (error) {
    return trimmed;
  }
}

function formatRotateLogTimestamp(timestamp) {
  const parsedTimestamp = new Date(timestamp);
  if (Number.isNaN(parsedTimestamp.getTime())) {
    return timestamp;
  }

  return parsedTimestamp.toLocaleString("ru-RU", {
    hour12: false,
  });
}

function buildRotateLogSignature(events) {
  return events.map((event) => String(event.timestamp || "")).join("|");
}

function renderRotateLog(events) {
  const emptyState = document.getElementById("rotate-log-empty");
  const logList = document.getElementById("rotate-log");

  if (!events.length) {
    emptyState.hidden = false;
    logList.innerHTML = "";
    return;
  }

  emptyState.hidden = true;
  logList.innerHTML = events.map((event) => `
    <li class="log-entry">
      <span class="log-entry-time">${escapeHtml(formatRotateLogTimestamp(event.timestamp || ""))}</span>
      <span class="log-entry-label">rotate</span>
    </li>
  `).join("");
}

async function loadRotateLog() {
  try {
    const response = await fetch(ROTATE_LOG_ENDPOINT, {
      headers: {
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      return;
    }

    const payload = await response.json();
    const events = Array.isArray(payload.events) ? payload.events : [];
    const nextSignature = buildRotateLogSignature(events);

    if (nextSignature === rotateLogSignature) {
      return;
    }

    rotateLogSignature = nextSignature;
    renderRotateLog(events);
  } catch (error) {
    // Keep the last successfully rendered log state.
  }
}

async function runAction(endpoint, resultId, button) {
  const resultBox = document.getElementById(resultId);
  const previousLabel = button.textContent;
  const shouldRefreshRotateLog = endpoint === "/rotate";

  button.disabled = true;
  button.textContent = "...";
  resultBox.value = "Выполняется запрос...";

  try {
    const response = await fetch(endpoint, {
      headers: {
        Accept: "application/json",
      },
    });

    const responseText = await response.text();
    const formatted = formatResponse(responseText);

    if (!response.ok) {
      resultBox.value = `HTTP ${response.status} ${response.statusText}\n${formatted}`;
      return;
    }

    resultBox.value = formatted;
  } catch (error) {
    resultBox.value = `Ошибка сети: ${error.message}`;
  } finally {
    button.disabled = false;
    button.textContent = previousLabel;

    if (shouldRefreshRotateLog) {
      void loadRotateLog();
    }
  }
}

renderRows();
void loadRotateLog();
window.setInterval(loadRotateLog, ROTATE_LOG_POLL_INTERVAL_MS);