// ── Dify Chatflow 연동 설정 ─────────────────────────────────────
// 주의: 이 키는 로컬 프로토타입 전용입니다. 실제 서비스에서는 절대
// 프론트엔드에 API 키를 노출하지 말고 백엔드 프록시를 통해 호출하세요.
// 상대 경로를 쓰는 이유: 이 페이지는 Caddy(tools/Caddyfile)가 정적 파일과 /v1/*
// 프록시를 같은 오리진(:8090)으로 묶어서 서빙합니다. "http://localhost/..."처럼
// 절대 주소를 박아두면 Cloudflare Tunnel 등으로 외부에서 접속했을 때 방문자
// 자신의 localhost를 가리키게 되어 무조건 실패합니다 — 상대 경로는 로컬이든
// 터널을 통한 외부 접속이든 항상 "지금 이 페이지를 서빙 중인 오리진"으로 풀립니다.
const DIFY_CHAT_API = "/v1/chat-messages";
const DIFY_CHAT_KEY = "app-d71tPzi9Bxk2G1EF2dwjTOSc";
const CHAT_USER = "meta-system-ui";

// 읽기 전용 목록조회 워크플로우(용어표준화-목록조회). 대화 상태가 필요 없는 단순 조회라
// LLM 분류 파이프라인을 타는 Chatflow 대신 1회성 /v1/workflows/run으로 분리했습니다.
const LIST_TERMS_API = "/v1/workflows/run";
const LIST_TERMS_KEY = "app-DEFsSJERD5Fav8qaSgrJa31i";
const STATUS_LABELS = { APPROVED: "승인", PENDING_REVIEW: "검토중", REJECTED: "반려" };

// 워크플로우 그래프의 실제 노드 순서(빌드 스크립트 build_chatflow.py 기준).
// 사용자에게는 내부 단계를 그대로 노출하지 않고 이해하기 쉬운 라벨로 보여줍니다.
const NODE_STEPS = [
  { id: "state", label: "이전 대화 상태 확인" },
  { id: "intent", label: "요청 의도 파악" },
  { id: "action", label: "업무 처리" },
  { id: "rag", label: "관련 자료 검색" },
  { id: "reply", label: "답변 작성" },
];

// standard_terms.domain에는 "수N7" 같은 데이터 도메인 코드만 들어있어 사람이 읽기 어렵습니다.
// 실제 카탈로그(data/scenario_catalog.json)의 4개 시나리오 도메인 설명을 화면 표시용으로 미러링합니다.
const DOMAIN_DESCRIPTIONS = {
  "수N7": "숫자 도메인 · 정수 7자리",
  "명V100": "명칭 도메인 · 문자열 최대 100자",
  "율N5,2": "비율 도메인 · 전체 5자리, 소수 2자리",
  "코드C2": "분류 코드 도메인 · 문자 2자리",
};

let chatConversationId = null;

// ── 상태 ────────────────────────────────────────────────────────
const state = {
  terms: [...MOCK_TERMS],
  activity: [...MOCK_ACTIVITY],
  history: [],
  chatRegisteredCount: 0,
};

// ── 네비게이션 ──────────────────────────────────────────────────
const VIEW_META = {
  dashboard: { title: "대시보드", subtitle: "용어 표준화 현황을 한눈에 확인하세요" },
  terms: { title: "용어 사전", subtitle: "등록된 표준 용어를 검색하고 관리합니다" },
  domains: { title: "도메인 관리", subtitle: "업무 도메인별 용어 분류 체계를 관리합니다" },
  history: { title: "표준화 이력", subtitle: "AI 파이프라인 실행 기록을 확인합니다" },
  settings: { title: "설정", subtitle: "백엔드 연동 정보를 확인합니다" },
};

function switchView(view) {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((section) => {
    section.hidden = section.id !== `view-${view}`;
  });
  document.getElementById("view-title").textContent = VIEW_META[view].title;
  document.getElementById("view-subtitle").textContent = VIEW_META[view].subtitle;
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

// ── 렌더링 ──────────────────────────────────────────────────────
function domainColor(domainName) {
  const d = MOCK_DOMAINS.find((x) => x.name === domainName);
  return d ? d.color : "#64748b";
}

function renderTermsTable() {
  const tbody = document.getElementById("terms-tbody");
  tbody.innerHTML = state.terms
    .map(
      (t) => `
    <tr class="${t.isNew ? "row-new" : ""}">
      <td><strong>${t.name}</strong></td>
      <td><span class="mono">${t.enAbbr || "-"}</span></td>
      <td class="cell-def">${t.def}</td>
      <td><span class="domain-tag" style="--tag-color:${domainColor(t.domain)}">${t.domain}</span></td>
      <td>${t.synonyms.length ? t.synonyms.join(", ") : "-"}</td>
      <td><span class="status-badge status-${t.status === "승인" ? "ok" : "pending"}">${t.status}</span></td>
      <td class="muted">${t.date}</td>
    </tr>`
    )
    .join("");
  document.getElementById("term-count-pill").textContent = `${state.terms.length}건`;
  document.getElementById("stat-total-terms").textContent = state.terms.length;
}

function renderDomainGrid() {
  const grid = document.getElementById("domain-grid");
  grid.innerHTML = MOCK_DOMAINS.map(
    (d) => `
    <div class="domain-card">
      <div class="domain-card-top">
        <span class="domain-dot" style="background:${d.color}"></span>
        <h3>${d.name}</h3>
      </div>
      <p>${d.desc}</p>
      <div class="domain-card-footer">
        <strong>${d.count}</strong>
        <span>등록된 용어</span>
      </div>
    </div>`
  ).join("");
}

function renderDomainBars() {
  const total = MOCK_DOMAINS.reduce((sum, d) => sum + d.count, 0);
  const wrap = document.getElementById("domain-bars");
  wrap.innerHTML = MOCK_DOMAINS.map((d) => {
    const pct = Math.round((d.count / total) * 100);
    return `
      <div class="bar-row">
        <span class="bar-label">${d.name}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${d.color}"></div></div>
        <span class="bar-value">${d.count}</span>
      </div>`;
  }).join("");
}

function renderActivity() {
  const list = document.getElementById("activity-list");
  list.innerHTML = state.activity
    .map(
      (a) => `
    <li>
      <div class="activity-dot"></div>
      <div>
        <p>${a.text}</p>
        <span class="muted">${a.who} · ${a.time}</span>
      </div>
    </li>`
    )
    .join("");
}

function renderHistory() {
  const list = document.getElementById("history-list");
  if (state.history.length === 0) {
    list.innerHTML = `<li class="empty-state">아직 처리된 이력이 없습니다. 우측 하단 챗봇으로 용어를 등록해보세요.</li>`;
    return;
  }
  list.innerHTML = state.history
    .map(
      (h) => `
    <li class="history-item">
      <div class="history-item-head">
        <strong>"${h.term}"</strong>
        <span class="muted">${h.time}</span>
      </div>
      <div class="history-steps">
        ${h.steps.map((s) => `<span class="step-chip step-${s.ok ? "ok" : "fail"}">${s.label}</span>`).join("")}
      </div>
    </li>`
    )
    .join("");
}

function renderAll() {
  renderTermsTable();
  renderDomainGrid();
  renderDomainBars();
  renderActivity();
  renderHistory();
}
renderAll();

// ── 실제 백엔드에서 용어 목록 조회 ──────────────────────────────
// standard_terms/registration_requests를 그대로 반영. 조회 실패 시(백엔드 미기동 등)
// 위에서 렌더링한 데모 데이터를 그대로 유지합니다.
function backendTermToRow(t) {
  return {
    id: `backend-${t.id}`,
    name: t.term_name,
    enAbbr: "",
    def: t.definition,
    domain: t.domain_description ? `${t.domain} (${t.domain_description})` : t.domain,
    synonyms: t.synonyms || [],
    status: STATUS_LABELS[t.status] || t.status,
    date: (t.created_at || "").slice(0, 10),
    isNew: false,
  };
}

async function fetchTermsFromBackend() {
  try {
    const res = await fetch(LIST_TERMS_API, {
      method: "POST",
      headers: { Authorization: `Bearer ${LIST_TERMS_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ inputs: {}, response_mode: "blocking", user: CHAT_USER }),
    });
    if (!res.ok) throw new Error(`목록 조회 실패 (${res.status})`);
    const payload = await res.json();
    const terms = payload.data?.outputs?.terms?.[0]?.terms;
    if (!Array.isArray(terms)) throw new Error("예상치 못한 응답 형식");
    state.terms = terms.map(backendTermToRow);
    renderAll();
  } catch (err) {
    console.warn("실제 백엔드에서 용어 목록을 불러오지 못해 데모 데이터를 유지합니다:", err);
  }
}
fetchTermsFromBackend();

// ── 챗봇 패널 열기/닫기 ─────────────────────────────────────────
const chatPanel = document.getElementById("chat-panel");
const chatFab = document.getElementById("chat-fab");

function openChat() {
  chatPanel.classList.add("is-open");
  document.getElementById("chat-input").focus();
}
chatFab.addEventListener("click", openChat);
document.getElementById("open-register-btn").addEventListener("click", openChat);
document.getElementById("chat-close").addEventListener("click", () => {
  chatPanel.classList.remove("is-open");
});

// ── Dify 관리자 콘솔 바로가기 ────────────────────────────────────
// runtime-config.js는 poc-start.ps1이 매번 새로 써주는 파일입니다. -Public으로
// 실행하면 Dify 스튜디오용 임시 터널 주소가, 아니면 로컬 주소가 들어갑니다.
function openDifyStudio() {
  const url = window.RUNTIME_CONFIG?.difyStudioUrl || "http://localhost/";
  window.open(url, "_blank", "noopener");
}
document.getElementById("dify-studio-nav-btn").addEventListener("click", openDifyStudio);
document.getElementById("open-dify-studio-btn").addEventListener("click", openDifyStudio);

// ── 채팅 UI 헬퍼 ────────────────────────────────────────────────
const chatBody = document.getElementById("chat-body");

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// 백엔드 LLM이 생성하는 답변에 **굵게**, "- " 목록, 줄바꿈이 섞여 있어 가볍게 마크다운을 렌더링합니다.
function formatAnswer(text) {
  const escaped = escapeHtml(text);
  const lines = escaped.split("\n");
  let html = "";
  let inList = false;
  for (const rawLine of lines) {
    const line = rawLine.trim();
    const bulletMatch = line.match(/^[-*]\s+(.*)$/);
    if (bulletMatch) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${bulletMatch[1]}</li>`;
      continue;
    }
    if (inList) { html += "</ul>"; inList = false; }
    if (line) html += `<p>${line}</p>`;
  }
  if (inList) html += "</ul>";
  return html
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^"'])"([^"]+)"/g, '$1"<em>$2</em>"');
}

function addUserMessage(text) {
  const el = document.createElement("div");
  el.className = "msg msg-user";
  el.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  chatBody.appendChild(el);
  scrollChatToBottom();
}

function addBotBubble(html) {
  const el = document.createElement("div");
  el.className = "msg msg-bot";
  el.innerHTML = `<div class="bubble">${html}</div>`;
  chatBody.appendChild(el);
  scrollChatToBottom();
  return el;
}

function setBubbleContent(bubbleWrap, html) {
  bubbleWrap.querySelector(".bubble").innerHTML = html;
  scrollChatToBottom();
}

function scrollChatToBottom() {
  chatBody.scrollTop = chatBody.scrollHeight;
}

function setChatStatus(text, tone) {
  const el = document.getElementById("chat-status");
  el.textContent = `● ${text}`;
  el.style.color = tone === "ok" ? "#059669" : tone === "error" ? "#dc2626" : "";
}

function addStepTracker() {
  const el = document.createElement("div");
  el.className = "msg msg-bot";
  el.innerHTML = `
    <div class="bubble bubble-steps">
      <ul class="step-tracker">
        ${NODE_STEPS.map((s) => `<li data-step="${s.id}"><span class="step-icon">○</span>${s.label}</li>`).join("")}
      </ul>
    </div>`;
  chatBody.appendChild(el);
  scrollChatToBottom();
  return el;
}

function setStepState(trackerEl, nodeId, status) {
  const li = trackerEl.querySelector(`li[data-step="${nodeId}"]`);
  if (!li) return;
  li.classList.remove("is-active", "is-done");
  li.classList.add(status === "done" ? "is-done" : "is-active");
  li.querySelector(".step-icon").textContent = status === "done" ? "●" : "◐";
}

// 백엔드가 stage별로 결정한 선택지를 클릭형 버튼으로 렌더링합니다. 목록에 원하는
// 답이 없으면 기존 입력창에 자유롭게 타이핑해서 보낼 수 있습니다.
function addOptionButtons(bubbleWrap, options, onPick) {
  const row = document.createElement("div");
  row.className = "option-row";
  row.innerHTML =
    options
      .map((o, i) => `<button type="button" class="option-chip" data-index="${i}">${escapeHtml(o.label)}</button>`)
      .join("") + `<span class="option-hint">해당하지 않으면 아래 입력창에 직접 입력하세요</span>`;
  bubbleWrap.querySelector(".bubble").appendChild(row);
  row.querySelectorAll(".option-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      row.querySelectorAll(".option-chip").forEach((b) => (b.disabled = true));
      onPick(options[Number(btn.dataset.index)].value);
    });
  });
  scrollChatToBottom();
}

// ── Dify Chatflow 스트리밍 호출 ─────────────────────────────────
// response_mode: "streaming"으로 호출하면 각 워크플로우 노드가 끝날 때마다
// node_finished 이벤트가 오고, action(apply_dify_turn) 노드에는 실제 MCP
// 결과(state)가 그대로 담겨 있어 별도 파싱 없이 그 값을 신뢰할 수 있습니다.
async function streamChatMessage(query, { onStep, onAnswerChunk } = {}) {
  const res = await fetch(DIFY_CHAT_API, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${DIFY_CHAT_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      inputs: {},
      response_mode: "streaming",
      conversation_id: chatConversationId || undefined,
      user: CHAT_USER,
    }),
  });

  if (!res.ok || !res.body) {
    const errText = await res.text().catch(() => res.statusText);
    throw new Error(`API 오류 (${res.status}): ${errText}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let answer = "";
  let mcpState = null;
  let options = [];

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex;
    while ((sepIndex = buffer.indexOf("\n\n")) >= 0) {
      const rawEvent = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);
      const dataLine = rawEvent.split("\n").find((l) => l.startsWith("data:"));
      if (!dataLine) continue;

      let payload;
      try {
        payload = JSON.parse(dataLine.slice(5).trim());
      } catch {
        continue;
      }

      if (payload.conversation_id) chatConversationId = payload.conversation_id;

      if (payload.event === "node_started" && payload.data?.node_id) {
        onStep?.(payload.data.node_id, "active");
      } else if (payload.event === "node_finished") {
        if (payload.data?.node_id) onStep?.(payload.data.node_id, "done");
        if (payload.data?.node_id === "action" && payload.data?.outputs?.state) {
          mcpState = payload.data.outputs.state;
        }
        if (payload.data?.node_id === "render_context" && payload.data?.outputs?.context) {
          try {
            options = JSON.parse(payload.data.outputs.context).options || [];
          } catch {
            /* malformed context JSON: fall back to free-text input only */
          }
        }
      } else if (payload.event === "message") {
        answer += payload.answer || "";
        onAnswerChunk?.(answer);
      } else if (payload.event === "error") {
        throw new Error(payload.message || "워크플로우 실행 중 오류가 발생했습니다.");
      }
    }
  }

  return { answer, state: mcpState, options };
}

// ── 등록 완료(state.stage === "submitted") 시 메타시스템에 실제 반영 ──
function handleRegistrationSubmitted(mcpState) {
  const reg = mcpState.registration;
  if (!reg || !reg.request_id) return;

  const domainCode = mcpState.domain || "";
  const domainLabel = DOMAIN_DESCRIPTIONS[domainCode]
    ? `${domainCode} (${DOMAIN_DESCRIPTIONS[domainCode]})`
    : domainCode || "미지정";

  state.terms.unshift({
    id: `chat-${reg.request_id}`,
    name: reg.term_name || mcpState.term_name,
    enAbbr: "",
    def: reg.definition || mcpState.definition,
    domain: domainLabel,
    synonyms: [],
    status: "검토중",
    date: (reg.created_at || new Date().toISOString()).slice(0, 10),
    isNew: true,
  });
  state.activity.unshift({
    text: `'${reg.term_name || mcpState.term_name}' 실제 백엔드로 등록 요청 (request_id: ${reg.request_id.slice(0, 8)}…)`,
    who: "AI 어시스턴트",
    time: "방금 전",
  });
  state.chatRegisteredCount += 1;
  document.getElementById("stat-chat-registered").textContent = state.chatRegisteredCount;
  renderAll();

  state.history.unshift({
    term: reg.term_name || mcpState.term_name,
    time: new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }),
    steps: NODE_STEPS.map((s) => ({ label: s.label, ok: true })),
  });
  renderHistory();
}

// ── 채팅 메시지 처리 ────────────────────────────────────────────
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

async function submitChatMessage(raw) {
  if (!raw) return;

  addUserMessage(raw);
  setChatStatus("처리 중", undefined);

  const tracker = addStepTracker();
  const bubble = addBotBubble('<p class="thinking">답변 작성 중...</p>');

  try {
    const { answer, state: mcpState, options } = await streamChatMessage(raw, {
      onStep: (nodeId, status) => setStepState(tracker, nodeId, status),
      onAnswerChunk: (partial) => setBubbleContent(bubble, formatAnswer(partial) || '<p class="thinking">답변 작성 중...</p>'),
    });

    setBubbleContent(bubble, formatAnswer(answer));
    tracker.remove();

    if (options && options.length) {
      addOptionButtons(bubble, options, (value) => submitChatMessage(value));
    }

    if (mcpState?.stage === "submitted") {
      handleRegistrationSubmitted(mcpState);
      fetchTermsFromBackend();
    }

    setChatStatus("연결됨", "ok");
    document.getElementById("api-status-dot").textContent = "● 정상 연결됨 (실제 Chatflow)";
    document.getElementById("api-status-dot").className = "status-dot status-ok";
  } catch (err) {
    tracker.remove();
    setBubbleContent(
      bubble,
      `<p>⚠️ 요청 처리 중 오류가 발생했습니다.</p><div class="result-card result-card-error">${escapeHtml(err.message)}</div><p class="hint">Dify(Docker)와 MCP 서버(8100)가 켜져 있는지 확인해주세요.</p>`
    );
    setChatStatus("연결 오류", "error");
    document.getElementById("api-status-dot").textContent = "● 연결 오류";
    document.getElementById("api-status-dot").className = "status-dot status-error";
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const raw = chatInput.value.trim();
  if (!raw) return;
  chatInput.value = "";
  submitChatMessage(raw);
});
