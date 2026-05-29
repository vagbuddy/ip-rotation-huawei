const ACTIONS = [
  { id: "status", title: "status", hint: "GET /status", input: "не требуется", endpoint: "/status", placeholder: "Здесь появится JSON-ответ" },
  { id: "public-ip", title: "public-ip", hint: "GET /public-ip", input: "не требуется", endpoint: "/public-ip", placeholder: "Здесь появится внешний IP" },
  { id: "mode-3g", title: "set-mode 3g", hint: "GET /mode/3g", input: "3g", endpoint: "/mode/3g", placeholder: "Ответ после переключения режима" },
  { id: "mode-4g", title: "set-mode 4g", hint: "GET /mode/4g", input: "4g", endpoint: "/mode/4g", placeholder: "Ответ после переключения режима" },
  { id: "mobile-on", title: "mobile-data on", hint: "GET /mobile-data/on", input: "1", endpoint: "/mobile-data/on", placeholder: "Ответ после включения mobile data" },
  { id: "mobile-off", title: "mobile-data off", hint: "GET /mobile-data/off", input: "0", endpoint: "/mobile-data/off", placeholder: "Ответ после выключения mobile data" },
  { id: "reconnect", title: "reconnect", hint: "GET /reconnect", input: "не требуется", endpoint: "/reconnect", placeholder: "Ответ после переподключения" },
  { id: "reboot", title: "reboot (modern)", hint: "GET /reboot", input: "ControlModeEnum.REBOOT", endpoint: "/reboot", placeholder: "Ответ после отправки команды reboot" },
];

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

async function runAction(endpoint, resultId, button) {
  const resultBox = document.getElementById(resultId);
  const previousLabel = button.textContent;

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
  }
}

renderRows();