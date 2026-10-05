const page = document.body.dataset.page;
const state = { conversationId: null };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[character]));
}

function status(message, tone = "info") {
  const element = document.getElementById("status");
  if (!element) return;
  element.textContent = message || "";
  element.dataset.tone = tone;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  let body = options.body;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }
  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    body,
  });
  if (response.status === 401 && page !== "login") {
    location.href = "/login";
    throw new Error("กรุณาเข้าสู่ระบบ");
  }
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!response.ok) {
    throw new Error(data?.detail || response.statusText);
  }
  return data;
}

async function logout() {
  await api("/auth/logout", { method: "POST" });
  location.href = "/login";
}

document.getElementById("logout")?.addEventListener("click", logout);

async function companies() {
  return (await api("/companies")).companies;
}

function fillCompanies(select, rows, includeAll = false) {
  select.replaceChildren();
  if (includeAll) select.append(new Option("ทุกบริษัท", ""));
  for (const company of rows) {
    const label = `${company.ticker}${company.name_en ? ` · ${company.name_en}` : ""}`;
    select.append(new Option(label, company.ticker));
  }
}

async function initLogin() {
  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await api("/auth/login", { method: "POST", json: values });
      location.href = "/chat";
    } catch (error) {
      status(error.message, "danger");
    }
  });
}

async function initChat() {
  const select = document.getElementById("company");
  const transcript = document.getElementById("transcript");
  const form = document.getElementById("chat-form");
  const textarea = form.elements.message;
  const rows = await companies();
  fillCompanies(select, rows);
  if (!rows.length) {
    status("ยังไม่มีบริษัท ไปหน้าดึงข้อมูล SET เพื่อเพิ่ม ticker ก่อน", "warning");
  } else {
    status("");
  }

  function resetChat() {
    state.conversationId = null;
    transcript.replaceChildren();
    const welcome = document.createElement("section");
    welcome.id = "chat-welcome";
    welcome.className = "chat-welcome";
    welcome.innerHTML = `
      <div class="assistant-mark">AI</div>
      <h1>วันนี้อยากวิเคราะห์ ${esc(select.value || "หุ้นตัวไหน")}</h1>
      <p>ถามจากเอกสาร ข้อมูล SET, Knowledge และ Investment Thesis ที่เก็บไว้</p>
      <div class="prompt-grid">
        <button type="button" class="prompt-suggestion">มีอะไรเปลี่ยนจาก Investment Thesis เดิมไหม</button>
        <button type="button" class="prompt-suggestion">สรุปปัจจัยเสี่ยงที่สำคัญ</button>
        <button type="button" class="prompt-suggestion">ทำไมบริษัทยังมี Growth</button>
        <button type="button" class="prompt-suggestion">เราเคยคุยอะไรเกี่ยวกับบริษัทนี้ไว้บ้าง</button>
      </div>`;
    transcript.append(welcome);
    bindSuggestions();
    status("");
  }

  function bindSuggestions() {
    document.querySelectorAll(".prompt-suggestion").forEach((button) => {
      button.addEventListener("click", () => {
        textarea.value = button.textContent;
        textarea.focus();
      });
    });
  }

  async function finishAndReset() {
    if (state.conversationId) {
      try {
        await api(`/conversations/${state.conversationId}/close`, { method: "POST" });
      } catch (error) {
        return status(error.message, "danger");
      }
    }
    resetChat();
  }

  function appendMessage(role, content, meta = "") {
    document.getElementById("chat-welcome")?.remove();
    const article = document.createElement("article");
    article.className = `chat-message ${role}`;
    article.innerHTML = `
      <div class="message-avatar">${role === "assistant" ? "AI" : "คุณ"}</div>
      <div class="message-body">
        <div class="message-name">${role === "assistant" ? "AI_VI" : "คุณ"}${meta ? `<span>${esc(meta)}</span>` : ""}</div>
        <pre>${esc(content)}</pre>
      </div>`;
    transcript.append(article);
    transcript.scrollTop = transcript.scrollHeight;
    return article;
  }

  select.addEventListener("change", finishAndReset);
  document.getElementById("new-chat").addEventListener("click", finishAndReset);
  bindSuggestions();

  textarea.addEventListener("input", () => {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  });
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!select.value) return status("เลือกหุ้นก่อนถาม", "warning");
    const message = new FormData(form).get("message").trim();
    if (!message) return;
    appendMessage("user", message);
    const thinking = appendMessage("assistant", "กำลังค้นข้อมูลและเรียบเรียงคำตอบ...");
    form.reset();
    textarea.style.height = "auto";
    status("");
    try {
      const payload = { message };
      if (state.conversationId) payload.conversation_id = state.conversationId;
      const result = await api(`/companies/${encodeURIComponent(select.value)}/chat`, {
        method: "POST",
        json: payload,
      });
      state.conversationId = result.conversation_id || state.conversationId;
      thinking.remove();
      appendMessage(
        "assistant",
        result.answer,
        `${result.intent} · LLM ${result.llm_calls}`,
      );
    } catch (error) {
      thinking.remove();
      status(error.message, "danger");
    }
  });
  document.getElementById("close-chat").addEventListener("click", async () => {
    if (!state.conversationId) return status("ยังไม่มีบทสนทนาที่เปิดอยู่", "warning");
    try {
      const result = await api(`/conversations/${state.conversationId}/close`, {
        method: "POST",
      });
      state.conversationId = null;
      status(`ปิดบทสนทนาและสร้างความจำ ${result.memories.length} รายการ`);
    } catch (error) {
      status(error.message, "danger");
    }
  });
}

async function initSetFetch() {
  const setStatus = await api("/api/set/status");
  const config = document.getElementById("set-config");
  config.textContent = setStatus.configured
    ? "SET_API_KEY พร้อมใช้งาน"
    : "ยังไม่มี SET_API_KEY ใน .env — สมัคร SET data API แล้วเพิ่มคีย์ก่อนดึงข้อมูลจริง";
  config.dataset.tone = setStatus.configured ? "success" : "warning";
  const rows = await companies();
  const datalist = document.getElementById("tickers");
  for (const company of rows) datalist.append(new Option("", company.ticker));
  document.getElementById("fetch-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const ticker = values.get("ticker").trim().toUpperCase();
    const name = values.get("name").trim();
    const dataTypes = values.getAll("data_type");
    if (!dataTypes.length) return status("เลือกชนิดข้อมูลอย่างน้อยหนึ่งรายการ", "warning");
    status(`กำลังดึง ${ticker} จาก SET...`);
    try {
      const existing = (await companies()).some((company) => company.ticker === ticker);
      if (!existing) {
        await api("/companies", {
          method: "POST",
          json: { ticker, market: "SET", name_en: name || null },
        });
      }
      const result = await api("/api/set/fetch", {
        method: "POST",
        json: { ticker, data_types: dataTypes },
      });
      renderFetchResult(result);
      status("ตรวจข้อมูลซ้ำเสร็จแล้ว");
    } catch (error) {
      status(error.message, "danger");
    }
  });
}

function renderFetchResult(result) {
  const container = document.getElementById("fetch-results");
  container.replaceChildren();
  for (const row of result.results) {
    const article = document.createElement("article");
    article.className = "data-card";
    article.innerHTML = `
      <div><strong>${esc(result.ticker)} · ${esc(row.data_type)}</strong></div>
      <span class="badge ${row.created ? "new" : "duplicate"}">${row.created ? "เพิ่มข้อมูลใหม่" : "ข้อมูลซ้ำ — ไม่เพิ่ม"}</span>
      <code>${esc(row.content_hash)}</code>`;
    container.append(article);
  }
}

async function initCompanyData() {
  const select = document.getElementById("company-filter");
  fillCompanies(select, await companies(), true);
  select.addEventListener("change", loadCompanyData);
  document.getElementById("refresh-data").addEventListener("click", loadCompanyData);
  await loadCompanyData();
}

async function loadCompanyData() {
  const ticker = document.getElementById("company-filter").value;
  status("กำลังโหลดคลังข้อมูล...");
  try {
    const query = ticker ? `?ticker=${encodeURIComponent(ticker)}` : "";
    const data = await api(`/api/company-data${query}`);
    renderCompanyData(data.companies);
    status(`พบ ${data.companies.length} บริษัท`);
  } catch (error) {
    status(error.message, "danger");
  }
}

function renderCompanyData(rows) {
  const container = document.getElementById("company-data-list");
  container.replaceChildren();
  if (!rows.length) {
    container.innerHTML = '<div class="empty">ยังไม่มีข้อมูลบริษัท</div>';
    return;
  }
  for (const item of rows) {
    const section = document.createElement("section");
    section.className = "company-section";
    const snapshots = item.snapshots.map((snapshot) => `
      <details>
        <summary>${esc(snapshot.data_type)} · ${new Date(snapshot.fetched_at).toLocaleString("th-TH")}</summary>
        <p class="muted">source: <a href="${esc(snapshot.source_url)}" target="_blank" rel="noreferrer">${esc(snapshot.source)}</a></p>
        <pre>${esc(JSON.stringify(snapshot.payload, null, 2))}</pre>
      </details>`).join("");
    const metrics = item.metrics.map((metric) =>
      `<tr><td>${esc(metric.metric_key)}</td><td>${esc(metric.period)}</td><td>${esc(metric.value)}</td><td>${esc(metric.unit)}</td></tr>`
    ).join("");
    const knowledge = item.knowledge.map((row) =>
      `<li><span class="badge">${esc(row.type)}</span> ${esc(row.statement)}</li>`
    ).join("");
    const documents = item.documents.map((row) =>
      `<li>${esc(row.title)} <span class="muted">${esc(row.doc_type)}</span></li>`
    ).join("");
    section.innerHTML = `
      <div class="company-title">
        <div><h2>${esc(item.company.ticker)}</h2><p>${esc(item.company.name_th || item.company.name_en || "")}</p></div>
        <span class="badge">${esc(item.company.market)}</span>
      </div>
      <div class="data-grid">
        <article class="panel-card"><h3>ข้อมูลจาก SET (${item.snapshots.length})</h3>${snapshots || '<p class="muted">ยังไม่มี snapshot</p>'}</article>
        <article class="panel-card"><h3>Metrics (${item.metrics.length})</h3>
          ${metrics ? `<div class="table-wrap"><table><thead><tr><th>Metric</th><th>Period</th><th>Value</th><th>Unit</th></tr></thead><tbody>${metrics}</tbody></table></div>` : '<p class="muted">ยังไม่มี metric</p>'}
        </article>
        <article class="panel-card"><h3>Knowledge (${item.knowledge.length})</h3><ul>${knowledge || '<li class="muted">ยังไม่มี knowledge</li>'}</ul></article>
        <article class="panel-card"><h3>Documents (${item.documents.length})</h3><ul>${documents || '<li class="muted">ยังไม่มีเอกสาร</li>'}</ul></article>
      </div>`;
    container.append(section);
  }
}

const initializers = {
  login: initLogin,
  chat: initChat,
  "set-fetch": initSetFetch,
  "company-data": initCompanyData,
};

initializers[page]?.().catch((error) => status(error.message, "danger"));
