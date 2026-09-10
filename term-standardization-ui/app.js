// ── Dify Chatflow 연동 설정 ─────────────────────────────────────
// 주의: 이 키는 로컬 프로토타입 전용입니다. 실제 서비스에서는 절대
// 프론트엔드에 API 키를 노출하지 말고 백엔드 프록시를 통해 호출하세요.
// 상대 경로를 쓰는 이유: 이 페이지는 Caddy(tools/Caddyfile)가 정적 파일과 /v1/*
// 프록시를 같은 오리진(:8090)으로 묶어서 서빙합니다. "http://localhost/..."처럼
// 절대 주소를 박아두면 Cloudflare Tunnel 등으로 외부에서 접속했을 때 방문자
// 자신의 localhost를 가리키게 되어 무조건 실패합니다 — 상대 경로는 로컬이든
// 터널을 통한 외부 접속이든 항상 "지금 이 페이지를 서빙 중인 오리진"으로 풀립니다.
const DIFY_CHAT_API = "/v1/chat-messages";
const DIFY_CHAT_KEY = "app-7MbTrZRjWuMz1uVc7y62E9kd";
const CHAT_USER = "meta-system-ui";

// 읽기 전용 목록조회 워크플로우(용어표준화-목록조회). 대화 상태가 필요 없는 단순 조회라
// LLM 분류 파이프라인을 타는 Chatflow 대신 1회성 /v1/workflows/run으로 분리했습니다.
const LIST_TERMS_API = "/v1/workflows/run";
const LIST_TERMS_KEY = "app-U0pwaq4eXx9buXrPLtrqoEF0";
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
  domains: { title: "도메인 관리", subtitle: "표준 용어에 적용되는 데이터 도메인(형식·길이) 체계를 관리합니다" },
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
// "도메인"은 백엔드(standard_terms.domain, domains 테이블)에 실제로 존재하는
// 단 하나의 개념 - 수N7/명V100/율N5,2/코드C2 같은 데이터 형식 도메인뿐입니다.
// 보건복지/행정/교육 같은 주제 분류는 백엔드 어디에도 없는 별개의 개념이라
// "도메인"이라는 이름으로 섞어 쓰면 안 됩니다. 여기서는 그 개념을 따로 만들지
// 않고, 지금 state.terms에 실제로 들어있는 도메인 값을 그대로 집계합니다.
const DOMAIN_PALETTE = ["#2563eb", "#7c3aed", "#059669", "#d97706", "#db2777", "#64748b"];

function computeDomainDistribution() {
  const counts = new Map();
  for (const t of state.terms) {
    counts.set(t.domain, (counts.get(t.domain) || 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([domain, count], i) => ({ domain, count, color: DOMAIN_PALETTE[i % DOMAIN_PALETTE.length] }));
}

function domainColor(domainName) {
  const d = state.domainDistribution.find((x) => x.domain === domainName);
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
  grid.innerHTML = state.domainDistribution
    .map(
      (d) => `
    <div class="domain-card">
      <div class="domain-card-top">
        <span class="domain-dot" style="background:${d.color}"></span>
        <h3>${d.domain}</h3>
      </div>
      <div class="domain-card-footer">
        <strong>${d.count}</strong>
        <span>등록된 용어</span>
      </div>
    </div>`
    )
    .join("");
}

function renderDomainBars() {
  const distribution = state.domainDistribution;
  const total = distribution.reduce((sum, d) => sum + d.count, 0) || 1;
  const wrap = document.getElementById("domain-bars");
  wrap.innerHTML = distribution
    .map((d) => {
      const pct = Math.round((d.count / total) * 100);
      return `
      <div class="bar-row">
        <span class="bar-label">${d.domain}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${d.color}"></div></div>
        <span class="bar-value">${d.count}</span>
      </div>`;
    })
    .join("");
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
        <span class="muted">${[a.who, a.time].filter(Boolean).join(" · ")}</span>
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
  // "관리 도메인"/"검토 대기"는 지금 실제로 조회된 state.terms에서 곧바로 센
  // 값입니다 - 카탈로그에 등록됐지만 용어가 하나도 없는 도메인은 여기 안
  // 잡힙니다(그런 도메인 목록은 프론트엔드가 조회할 방법이 아직 없음).
  state.domainDistribution = computeDomainDistribution();
  renderTermsTable();
  renderDomainGrid();
  renderDomainBars();
  renderActivity();
  renderHistory();
  const domainCountEl = document.getElementById("stat-domain-count");
  if (domainCountEl) domainCountEl.textContent = state.domainDistribution.length;
  const pendingEl = document.getElementById("stat-pending-review");
  if (pendingEl) pendingEl.textContent = state.terms.filter((t) => t.status === "검토중").length;
}
renderAll();

// ── 실제 백엔드에서 용어 목록 조회 ──────────────────────────────
// standard_terms/registration_requests를 그대로 반영. 조회 실패 시(백엔드 미기동 등)
// 위에서 렌더링한 데모 데이터를 그대로 유지합니다.
function backendTermToRow(t) {
  return {
    id: `backend-${t.id}`,
    name: t.term_name,
    enAbbr: t.english_abbr || "",
    def: t.definition,
    domain: t.domain,
    synonyms: t.synonyms || [],
    status: STATUS_LABELS[t.status] || t.status,
    statusCode: t.status,
    date: (t.created_at || "").slice(0, 10),
    createdAt: t.created_at || "",
    isNew: false,
  };
}

// ── 최근 등록 활동(대시보드) ────────────────────────────────────
// 가짜 이름을 지어내는 대신, 실제 조회된 용어 목록의 created_at/status를
// 그대로 최신순으로 보여줍니다. 이 시스템엔 로그인/담당자 식별이 없어서
// "누가"는 알 수 없으니, 대신 실제 값인 도메인을 부제로 보여줍니다.
const ACTIVITY_VERBS = {
  APPROVED: "표준 용어로 등록됨",
  PENDING_REVIEW: "신규 등록 요청 (검토 대기)",
  REJECTED: "등록 반려됨",
};

function relativeTime(isoString) {
  const then = isoString ? new Date(isoString).getTime() : NaN;
  if (Number.isNaN(then)) return "";
  const diffMin = Math.floor(Math.max(0, Date.now() - then) / 60000);
  if (diffMin < 1) return "방금 전";
  if (diffMin < 60) return `${diffMin}분 전`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}시간 전`;
  const diffDay = Math.floor(diffHour / 24);
  return `${diffDay}일 전`;
}

function activityFromTerms(terms, limit = 6) {
  return [...terms]
    .filter((t) => t.createdAt)
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))
    .slice(0, limit)
    .map((t) => ({
      text: `'${t.name}' ${ACTIVITY_VERBS[t.statusCode] || "등록"}`,
      who: t.domain,
      time: relativeTime(t.createdAt),
    }));
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
    state.activity = activityFromTerms(state.terms);
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

// ── 챗봇 패널 폭 조절 (드래그 + 기억) ────────────────────────────
const chatResizeHandle = document.getElementById("chat-resize-handle");
const CHAT_WIDTH_STORAGE_KEY = "chatPanelWidth";
const CHAT_MIN_WIDTH = 360;

function chatMaxWidth() {
  return Math.min(900, Math.round(window.innerWidth * 0.92));
}

function setChatWidth(px) {
  const clamped = Math.min(chatMaxWidth(), Math.max(CHAT_MIN_WIDTH, Math.round(px)));
  document.documentElement.style.setProperty("--chat-width", `${clamped}px`);
  return clamped;
}

(function restoreChatWidth() {
  try {
    const saved = Number(localStorage.getItem(CHAT_WIDTH_STORAGE_KEY));
    if (saved) setChatWidth(saved);
  } catch {
    /* localStorage unavailable (private mode etc.) - default width from CSS applies */
  }
})();

chatResizeHandle.addEventListener("pointerdown", (e) => {
  chatResizeHandle.setPointerCapture(e.pointerId);
  chatPanel.classList.add("is-resizing");
  e.preventDefault();
});
chatResizeHandle.addEventListener("pointermove", (e) => {
  if (!chatResizeHandle.hasPointerCapture(e.pointerId)) return;
  // Panel is anchored to the viewport's right edge, so its width is simply
  // the distance from the cursor to that edge.
  setChatWidth(window.innerWidth - e.clientX);
});
function finishChatResize(e) {
  if (!chatResizeHandle.hasPointerCapture(e.pointerId)) return;
  chatResizeHandle.releasePointerCapture(e.pointerId);
  chatPanel.classList.remove("is-resizing");
  try {
    const current = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--chat-width"), 10);
    if (current) localStorage.setItem(CHAT_WIDTH_STORAGE_KEY, String(current));
  } catch {
    /* ignore persistence failure */
  }
}
chatResizeHandle.addEventListener("pointerup", finishChatResize);
chatResizeHandle.addEventListener("pointercancel", finishChatResize);

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

// ── 구조화된 데이터 렌더링 ────────────────────────────────────
// 도메인 추천, 유사 용어 비교, 최종 등록 요약처럼 매번 같은 형식으로
// 반복되는 응답은 LLM 문장을 파싱하는 대신 action 노드가 돌려주는 실제
// MCP state를 직접 표/카드로 그려서, 매번 정확히 같은 모양을 보장합니다.
const RELATION_LABEL = { SAME_MEANING: "동일 의미", RELATED_BUT_DISTINCT: "관련 있으나 구분", UNCERTAIN: "판단 보류" };

function renderDomainTable(domains) {
  if (!domains) return "";
  const rows = [];
  const shown = new Set();
  for (const d of domains.distribution || []) {
    shown.add(d.domain);
    rows.push({ code: d.domain, desc: d.domain_description, evidence: `${d.count}/${domains.sample_size}건`, ratio: d.ratio, recommended: d.domain === domains.recommended_domain });
  }
  for (const d of domains.known_domains || []) {
    if (shown.has(d.code)) continue;
    rows.push({ code: d.code, desc: d.description, evidence: "비교 근거 없음", ratio: null, recommended: false });
  }
  if (!rows.length) return "";
  return `<div class="table-wrap"><table class="data-table">
    <thead><tr><th>도메인</th><th>설명</th><th>비교군 사용</th><th>관측 비율</th></tr></thead>
    <tbody>${rows.map((r) => `
      <tr class="${r.recommended ? "row-new" : ""}">
        <td><span class="mono">${escapeHtml(r.code)}</span>${r.recommended ? '<span class="tag-recommend">추천</span>' : ""}</td>
        <td class="cell-def">${escapeHtml(r.desc || "설명 없음")}</td>
        <td>${escapeHtml(r.evidence)}</td>
        <td>${r.ratio == null ? "-" : Math.round(r.ratio * 100) + "%"}</td>
      </tr>`).join("")}</tbody>
  </table></div>`;
}

function renderComparisonTable(mcpState) {
  const prep = mcpState.preparation || {};
  const assessment = prep.assessment || prep;
  const comparisons = assessment.comparisons || [];
  const candidatesById = {};
  for (const c of (assessment.search || {}).candidates || []) candidatesById[c.term_id] = c;
  const rows = comparisons
    .filter((c) => c.relation !== "DISTINCT")
    .map((c) => ({ ...c, cand: candidatesById[c.existing_term_id] }))
    .filter((r) => r.cand);
  if (!rows.length) return "";
  return `<div class="table-wrap"><table class="data-table">
    <thead><tr><th>기존 용어</th><th>도메인</th><th>정의</th><th>판정</th><th>신뢰도</th></tr></thead>
    <tbody>${rows.map((r) => `
      <tr>
        <td><strong>${escapeHtml(r.cand.name)}</strong></td>
        <td><span class="mono">${escapeHtml(r.cand.domain)}</span></td>
        <td class="cell-def">${escapeHtml(r.cand.definition)}<div class="cell-note">사유: ${escapeHtml(r.reason || "-")}</div></td>
        <td><span class="relation-badge relation-${r.relation.toLowerCase()}">${RELATION_LABEL[r.relation] || r.relation}</span></td>
        <td>${Math.round((r.confidence || 0) * 100)}%</td>
      </tr>`).join("")}</tbody>
  </table></div>`;
}

function summaryCard(rows, extraClass = "") {
  const filtered = rows.filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (!filtered.length) return "";
  return `<div class="summary-card ${extraClass}">${filtered
    .map(([k, v, mono]) => `<div class="summary-row"><span class="summary-key">${escapeHtml(k)}</span><span class="summary-val${mono ? " mono" : ""}">${escapeHtml(String(v))}</span></div>`)
    .join("")}</div>`;
}

function renderConfirmSummary(mcpState) {
  return summaryCard([
    ["용어명", mcpState.term_name],
    ["정의", mcpState.definition],
    ["도메인", mcpState.domain, true],
    ["영문 약어", mcpState.english_abbr, true],
  ]);
}

function renderGuidelineCard(mcpState) {
  const rows = [];
  for (const v of (mcpState.validation || {}).violations || []) rows.push({ tag: "표기 규칙", reason: v.reason });
  const gc = mcpState.guideline_check;
  if (gc && gc.compliant === false) rows.push({ tag: gc.violated_section || "표준가이드", reason: gc.reason });
  if (!rows.length) return "";
  const suggestion = (mcpState.validation || {}).suggestions?.[0] || gc?.suggested_term || "";
  return `<div class="violation-card">
    ${rows.map((r) => `<div class="violation-row"><span class="violation-tag">${escapeHtml(r.tag)}</span><span>${escapeHtml(r.reason)}</span></div>`).join("")}
    ${suggestion ? `<div class="violation-suggestion">제안 용어: <strong>${escapeHtml(suggestion)}</strong></div>` : ""}
  </div>`;
}

function renderDefinitionSuggestionCard(mcpState) {
  const sug = mcpState.definition_suggestion;
  if (!sug) return "";
  if (sug.ambiguous && (sug.options || []).length) {
    return `<div class="question-card"><strong>확인이 필요합니다</strong>${escapeHtml(sug.question || "")}</div>`;
  }
  if (sug.definition) {
    return `<div class="definition-card"><p>${escapeHtml(sug.definition)}</p>${sug.rationale ? `<div class="cell-note">${escapeHtml(sug.rationale)}</div>` : ""}</div>`;
  }
  return "";
}

function renderAbbreviationCard(mcpState) {
  const sug = mcpState.abbreviation_suggestion;
  if (!sug || !sug.abbreviation) return "";
  return `<div class="abbr-card"><div class="abbr-code">${escapeHtml(sug.abbreviation)}</div><div class="abbr-rationale">${escapeHtml(sug.rationale || "")}</div></div>`;
}

function renderPendingCard(mcpState) {
  const p = mcpState.pending_request;
  if (!p) return "";
  return summaryCard([
    ["용어명", p.term_name],
    ["정의", p.definition],
    ["도메인", p.domain, true],
    ["영문 약어", p.english_abbr, true],
    ["제출일", (p.created_at || "").slice(0, 10)],
  ]);
}

function renderRegistrationCard(mcpState) {
  const reg = mcpState.registration;
  if (!reg) return "";
  if (reg.request_id) {
    return summaryCard([
      ["신청 ID", reg.request_id.slice(0, 8) + "…", true],
      ["용어명", reg.term_name || mcpState.term_name],
      ["도메인", reg.domain || mcpState.domain, true],
      ["영문 약어", reg.english_abbr || mcpState.english_abbr, true],
      ["상태", "검토 대기 (PENDING_REVIEW)"],
    ], "summary-card-ok");
  }
  return summaryCard([["실패 사유 코드", reg.code, true]], "summary-card-fail");
}

// stage별로 어떤 구조화 블록을 붙일지 결정합니다. 서버(build_chatflow.py의
// RENDER 프롬프트)는 이 stage들에서 같은 내용을 문장으로 다시 나열하지
// 않도록 되어 있어, 프론트엔드 표/카드가 유일한 상세 정보 출처입니다.
function renderStructuredBlock(mcpState) {
  if (!mcpState) return "";
  switch (mcpState.stage) {
    case "awaiting_domain_choice":
      return renderDomainTable(mcpState.domains);
    case "awaiting_definition":
      return renderDefinitionSuggestionCard(mcpState);
    case "awaiting_confirm":
      return renderComparisonTable(mcpState) + renderConfirmSummary(mcpState);
    case "existing_term_found":
    case "definition_blocked":
      return renderComparisonTable(mcpState);
    case "awaiting_guideline_choice":
      return renderGuidelineCard(mcpState);
    case "awaiting_abbreviation":
      return renderAbbreviationCard(mcpState);
    case "pending_request_found":
      return renderPendingCard(mcpState);
    case "submitted":
    case "registration_failed":
      return renderRegistrationCard(mcpState);
    default:
      return "";
  }
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
        // options is its own node output (not nested in .context) so the reply-
        // rendering LLM's prompt never sees the option labels' full descriptive
        // text and can't copy it into prose - see render_context's own comment.
        if (payload.data?.node_id === "render_context" && payload.data?.outputs?.options) {
          try {
            options = JSON.parse(payload.data.outputs.options) || [];
          } catch {
            /* malformed options JSON: fall back to free-text input only */
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

  const domainCode = mcpState.domain || "미지정";
  const createdAt = reg.created_at || new Date().toISOString();

  state.terms.unshift({
    id: `chat-${reg.request_id}`,
    name: reg.term_name || mcpState.term_name,
    enAbbr: reg.english_abbr || mcpState.english_abbr || "",
    def: reg.definition || mcpState.definition,
    domain: domainCode,
    synonyms: [],
    status: "검토중",
    date: createdAt.slice(0, 10),
    createdAt,
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

    const structuredHtml = renderStructuredBlock(mcpState);
    if (structuredHtml) {
      bubble.querySelector(".bubble").classList.add("has-data");
      bubble.querySelector(".bubble").insertAdjacentHTML("beforeend", structuredHtml);
      scrollChatToBottom();
    }

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
