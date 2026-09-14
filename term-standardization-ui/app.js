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
let currentView = "dashboard";

// ── 상태 ────────────────────────────────────────────────────────
// termsPage/wordsPage는 각자 독립된 페이지네이션 상태(limit/offset/q/total) -
// 용어사전과 단어사전은 서로 다른 화면이라 검색어·페이지 위치가 섞이면 안 됨.
// domains는 list_data_domains 전체(126건, 페이지네이션 불필요)를 그대로 담으며
// 각 항목에 실제 전체 term_count(백엔드 LEFT JOIN 집계)가 포함된다 - 도메인
// 관리 카드와 대시보드 막대차트 둘 다 이 하나의 소스만 쓴다.
const state = {
  terms: [...MOCK_TERMS],
  words: [],
  domains: [],
  termsPage: { limit: 50, offset: 0, total: 0, q: "" },
  wordsPage: { limit: 50, offset: 0, total: 0, q: "" },
  activity: [...MOCK_ACTIVITY],
  history: [],
  chatRegisteredCount: 0,
};

// ── 네비게이션 ──────────────────────────────────────────────────
const VIEW_META = {
  dashboard: { title: "대시보드", subtitle: "용어 표준화 현황을 한눈에 확인하세요" },
  terms: { title: "용어 사전", subtitle: "등록된 표준 용어를 검색하고 관리합니다" },
  words: { title: "단어 사전", subtitle: "용어를 구성하는 표준단어(標準單語)를 검색하고 관리합니다" },
  domains: { title: "도메인 관리", subtitle: "표준 용어에 적용되는 데이터 도메인(형식·길이) 체계를 관리합니다" },
  history: { title: "표준화 이력", subtitle: "AI 파이프라인 실행 기록을 확인합니다" },
  settings: { title: "설정", subtitle: "백엔드 연동 정보를 확인합니다" },
};

function switchView(view) {
  currentView = view;
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((section) => {
    section.hidden = section.id !== `view-${view}`;
  });
  document.getElementById("view-title").textContent = VIEW_META[view].title;
  document.getElementById("view-subtitle").textContent = VIEW_META[view].subtitle;
  // 검색창은 용어사전/단어사전 화면 전용 - 다른 화면으로 전환된 동안 자기 검색어를
  // 잊지 않도록 각자 상태에 보관해뒀다가, 그 화면으로 돌아오면 그대로 복원한다.
  const searchInput = document.getElementById("global-search-input");
  if (searchInput) {
    if (view === "words") {
      searchInput.value = state.wordsPage.q;
      searchInput.placeholder = "단어명·정의로 검색...";
    } else if (view === "terms") {
      searchInput.value = state.termsPage.q;
      searchInput.placeholder = "용어명·정의로 검색...";
    } else {
      searchInput.value = "";
      searchInput.placeholder = "용어 사전 또는 단어사전 화면에서 이름·정의로 검색...";
    }
  }
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

// ── 렌더링 ──────────────────────────────────────────────────────
// "도메인"은 백엔드(standard_terms.domain, domains 테이블)에 실제로 존재하는
// 단 하나의 개념 - 수N7/명V100/율N5,2/코드C2 같은 데이터 형식 도메인뿐입니다.
// 보건복지/행정/교육 같은 주제 분류는 백엔드 어디에도 없는 별개의 개념이라
// "도메인"이라는 이름으로 섞어 쓰면 안 됩니다.
//
// 도메인별 용어수는 반드시 state.domains(list_data_domains()가 돌려주는 실제
// 전체 도메인 + term_count, tools.py에서 LEFT JOIN으로 집계한 진짜 전체 합계)
// 에서만 가져온다 - 예전엔 지금 로드된 state.terms(페이지당 50건)만 세는
// computeDomainDistribution()을 썼는데, 카탈로그가 13,000건대로 커지면서
// "도메인 수도, 도메인별 건수도 다 틀리다"는 버그로 실제로 드러났다. 절대
// 페이지 단위로 로드된 용어 목록에서 도메인 분포를 다시 집계하지 말 것.
const DOMAIN_PALETTE = ["#2563eb", "#7c3aed", "#059669", "#d97706", "#db2777", "#0891b2", "#65a30d", "#ea580c"];

// 도메인 코드 문자열을 해시해 항상 같은 색을 돌려준다 - "상위 N개 안에 드는지"
// 같은 순위에 색을 의존시키면, 정렬이나 필터가 바뀔 때마다 같은 도메인인데
// 다른 색으로 보이는 문제가 생긴다.
function domainColor(code) {
  let hash = 0;
  for (let i = 0; i < code.length; i++) hash = (hash * 31 + code.charCodeAt(i)) >>> 0;
  return DOMAIN_PALETTE[hash % DOMAIN_PALETTE.length];
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
  // total은 실제 백엔드 total_count(전체 카탈로그 건수) - 화면에 그려진 현재
  // 페이지 행 수(state.terms.length)와는 다르다. 백엔드 조회 전(목업 데이터
  // 표시 중)에는 total이 아직 0이라 페이지 길이로 대체한다.
  const total = state.termsPage.total || state.terms.length;
  document.getElementById("term-count-pill").textContent = `${total.toLocaleString()}건`;
  document.getElementById("stat-total-terms").textContent = total.toLocaleString();
}

function renderWordsTable() {
  const tbody = document.getElementById("words-tbody");
  if (!tbody) return;
  tbody.innerHTML = state.words
    .map(
      (w) => `
    <tr>
      <td><strong>${w.name}</strong></td>
      <td><span class="mono">${w.enAbbr || "-"}</span></td>
      <td>${w.enName || "-"}</td>
      <td class="cell-def">${w.def || "-"}</td>
      <td>${w.isFormatWord ? "예" : "-"}</td>
      <td>${w.domainClassification || "-"}</td>
      <td><span class="status-badge status-${w.status === "ACTIVE" ? "ok" : "pending"}">${w.status === "ACTIVE" ? "사용중" : w.status}</span></td>
    </tr>`
    )
    .join("");
  const total = state.wordsPage.total || state.words.length;
  const pill = document.getElementById("word-count-pill");
  if (pill) pill.textContent = `${total.toLocaleString()}건`;
}

// terms/words 공통 페이지네이션 렌더링 - 이전/다음 버튼과 "n건 중 a-b" 라벨.
function renderPagination(containerId, page, onPrev, onNext) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const from = page.total === 0 ? 0 : page.offset + 1;
  const to = Math.min(page.offset + page.limit, page.total);
  el.innerHTML = `
    <button class="btn-ghost" id="${containerId}-prev" ${page.offset <= 0 ? "disabled" : ""}>이전</button>
    <span class="pagination-label">${page.total.toLocaleString()}건 중 ${from}-${to}</span>
    <button class="btn-ghost" id="${containerId}-next" ${page.offset + page.limit >= page.total ? "disabled" : ""}>다음</button>`;
  document.getElementById(`${containerId}-prev`).addEventListener("click", onPrev);
  document.getElementById(`${containerId}-next`).addEventListener("click", onNext);
}

function changeTermsPage(delta) {
  state.termsPage.offset = Math.max(0, state.termsPage.offset + delta * state.termsPage.limit);
  fetchCatalogFromBackend();
}
function changeWordsPage(delta) {
  state.wordsPage.offset = Math.max(0, state.wordsPage.offset + delta * state.wordsPage.limit);
  fetchCatalogFromBackend();
}

// "도메인 관리" 화면 전용 - list_data_domains가 돌려주는 실제 활성 도메인
// 전체(126건)와, 각 도메인의 진짜 전체 term_count를 그대로 카드로 그린다.
function renderDomainGrid() {
  const grid = document.getElementById("domain-grid");
  grid.innerHTML = state.domains
    .map(
      (d) => `
    <div class="domain-card">
      <div class="domain-card-top">
        <span class="domain-dot" style="background:${domainColor(d.code)}"></span>
        <h3>${escapeHtml(d.code)}</h3>
      </div>
      <p class="muted">${escapeHtml(d.description || "-")}</p>
      <div class="domain-card-footer">
        <strong>${(d.term_count || 0).toLocaleString()}</strong>
        <span>건 사용 중</span>
      </div>
    </div>`
    )
    .join("");
  const pill = document.getElementById("domain-count-pill");
  if (pill) pill.textContent = `${state.domains.length.toLocaleString()}건`;
}

// 대시보드는 요약용 작은 패널이라 126개 도메인을 다 나열하면 UX가 나빠진다 -
// 건수 상위 몇 개만 막대로 보여주고, 나머지는 "그 외 N개" 한 줄로 합산한 뒤
// "도메인 관리" 화면으로 바로 넘어갈 수 있는 링크를 둔다(페이지네이션보다
// 이 작은 패널에는 더 적합한 요약+드릴다운 패턴).
const DASHBOARD_DOMAIN_TOP_N = 8;

function renderDomainBars() {
  const wrap = document.getElementById("domain-bars");
  if (!wrap) return;
  const used = state.domains.filter((d) => (d.term_count || 0) > 0).sort((a, b) => b.term_count - a.term_count);
  const total = used.reduce((sum, d) => sum + d.term_count, 0) || 1;
  const top = used.slice(0, DASHBOARD_DOMAIN_TOP_N);
  const rest = used.slice(DASHBOARD_DOMAIN_TOP_N);
  const restSum = rest.reduce((sum, d) => sum + d.term_count, 0);
  let html = top
    .map((d) => {
      const pct = Math.round((d.term_count / total) * 100);
      return `
      <div class="bar-row">
        <span class="bar-label" title="${escapeHtml(d.description || "")}">${escapeHtml(d.code)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${domainColor(d.code)}"></div></div>
        <span class="bar-value">${d.term_count.toLocaleString()}</span>
      </div>`;
    })
    .join("");
  if (rest.length) {
    const pct = Math.round((restSum / total) * 100);
    html += `
      <div class="bar-row">
        <span class="bar-label muted">그 외 ${rest.length}개 도메인</span>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:#cbd5e1"></div></div>
        <span class="bar-value">${restSum.toLocaleString()}</span>
      </div>
      <button class="btn-ghost domain-bars-more" id="domain-bars-view-all">전체 도메인 보기 (${state.domains.length}건)</button>`;
  }
  wrap.innerHTML = html || `<p class="muted">아직 도메인별 용어 데이터가 없습니다.</p>`;
  document.getElementById("domain-bars-view-all")?.addEventListener("click", () => switchView("domains"));
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
  renderTermsTable();
  renderWordsTable();
  renderDomainGrid();
  renderDomainBars();
  renderActivity();
  renderHistory();
  renderPagination("terms-pagination", state.termsPage, () => changeTermsPage(-1), () => changeTermsPage(1));
  renderPagination("words-pagination", state.wordsPage, () => changeWordsPage(-1), () => changeWordsPage(1));
  // "관리 도메인" 통계는 실제 전체 활성 도메인 수(state.domains, 백엔드 응답 전엔 0).
  const domainCountEl = document.getElementById("stat-domain-count");
  if (domainCountEl) domainCountEl.textContent = state.domains.length.toLocaleString();
  const pendingEl = document.getElementById("stat-pending-review");
  if (pendingEl) pendingEl.textContent = state.terms.filter((t) => t.status === "검토중").length;
}
renderAll();

// ── 실제 백엔드에서 카탈로그 조회 ──────────────────────────────
// standard_terms/registration_requests/standard_words/domains를 그대로 반영.
// 조회 실패 시(백엔드 미기동 등) 위에서 렌더링한 데모 데이터를 그대로 유지합니다.
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

function backendWordToRow(w) {
  return {
    name: w.name,
    enAbbr: w.english_abbr || "",
    enName: w.english_name || "",
    def: w.definition || "",
    isFormatWord: !!w.is_format_word,
    domainClassification: w.domain_classification || "",
    status: w.status,
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

// 용어/단어/도메인 셋 다 이 워크플로 하나가 한 번에 돌려준다(build_list_terms_workflow.py
// 참고) - 매번 세 개를 다 요청하는 게 약간 낭비처럼 보일 수 있지만, 페이지당
// 최대 200건씩이라 비용이 작고, 앱 3개를 따로 배포/키관리하는 것보다 훨씬 단순하다.
async function fetchCatalogFromBackend() {
  try {
    const res = await fetch(LIST_TERMS_API, {
      method: "POST",
      headers: { Authorization: `Bearer ${LIST_TERMS_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        inputs: {
          limit: state.termsPage.limit, offset: state.termsPage.offset, q: state.termsPage.q,
          words_limit: state.wordsPage.limit, words_offset: state.wordsPage.offset, words_q: state.wordsPage.q,
        },
        response_mode: "blocking", user: CHAT_USER,
      }),
    });
    if (!res.ok) throw new Error(`목록 조회 실패 (${res.status})`);
    const payload = await res.json();
    const outputs = payload.data?.outputs || {};
    const termsResult = outputs.terms?.[0];
    const wordsResult = outputs.words?.[0];
    const domainsResult = outputs.domains?.[0];
    if (!termsResult || !Array.isArray(termsResult.terms)) throw new Error("예상치 못한 응답 형식(terms)");
    state.terms = termsResult.terms.map(backendTermToRow);
    state.termsPage.total = termsResult.total_count ?? state.terms.length;
    if (wordsResult && Array.isArray(wordsResult.words)) {
      state.words = wordsResult.words.map(backendWordToRow);
      state.wordsPage.total = wordsResult.total_count ?? state.words.length;
    }
    if (domainsResult && Array.isArray(domainsResult.domains)) {
      state.domains = domainsResult.domains;
    }
    state.activity = activityFromTerms(state.terms);
    renderAll();
  } catch (err) {
    console.warn("실제 백엔드에서 카탈로그를 불러오지 못해 데모 데이터를 유지합니다:", err);
  }
}
fetchCatalogFromBackend();

// 상단바 검색창은 지금 열려 있는 화면(용어사전/단어사전)에 맞는 검색어로
// 취급한다. 타이핑마다 재조회하면 낭비니 300ms 디바운스.
let searchDebounceTimer = null;
document.getElementById("global-search-input")?.addEventListener("input", (e) => {
  const value = e.target.value;
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    if (currentView === "words") {
      state.wordsPage.q = value;
      state.wordsPage.offset = 0;
    } else if (currentView === "terms") {
      state.termsPage.q = value;
      state.termsPage.offset = 0;
    } else {
      return;
    }
    fetchCatalogFromBackend();
  }, 300);
});

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
const CHAT_INITIAL_HTML = chatBody.innerHTML;

// 여러 용어를 연달아 등록하다 보면 이전 대화의 상태(선택한 도메인, 추천받은
// 정의/약어 등)가 새 요청과 뒤섞여 엉뚱한 답변으로 이어질 수 있습니다 - 새
// Dify conversation_id로 완전히 새로 시작해서 그 가능성을 원천 차단합니다.
document.getElementById("chat-reset").addEventListener("click", () => {
  chatConversationId = null;
  chatBody.innerHTML = CHAT_INITIAL_HTML;
  setChatStatus("대기 중", undefined);
  chatInput.focus();
});

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
  // distribution은 이미 백엔드(domain_usage())에서 "실제 비교군에 1건이라도 등장한
  // 도메인"만 담고 있음 - 여기서는 그중 상위 10개까지만 보여준다. 후보가 30건까지
  // 모일 수 있어서 서로 다른 도메인이 10개를 넘어갈 수 있음.
  for (const d of (domains.distribution || []).slice(0, 10)) {
    rows.push({ code: d.domain, desc: d.domain_description, evidence: `${d.count}/${domains.sample_size}건`, ratio: d.ratio, recommended: d.domain === domains.recommended_domain });
  }
  // 비교 근거가 하나도 없을 때만 - 그래도 뭐라도 고를 수 있게 전체 도메인 중 5개까지 폴백.
  // 근거가 있는데 카탈로그 전체(최대 126개)를 다 나열하던 게 원래 버그였음.
  if (!rows.length) {
    for (const d of (domains.known_domains || []).slice(0, 5)) {
      rows.push({ code: d.code, desc: d.description, evidence: "비교 근거 없음", ratio: null, recommended: false });
    }
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
  // 신뢰도 높은 순으로 정렬 후 상위 10건만 - 후보가 최대 30건까지 모여서 비교
  // 결과가 그만큼 나올 수 있는데, 실제로 봐야 할 건 가장 유사한 소수뿐이다.
  const rows = comparisons
    .filter((c) => c.relation !== "DISTINCT")
    .map((c) => ({ ...c, cand: candidatesById[c.existing_term_id] }))
    .filter((r) => r.cand)
    .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
    .slice(0, 10);
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

function renderExistingTermCard(mcpState) {
  const search = mcpState.search || {};
  const match = search.exact_matches?.[0] || search.synonym_matches?.[0];
  if (!match) return "";
  return summaryCard([
    ["용어명", match.name],
    ["정의", match.definition],
    ["도메인", match.domain, true],
    ["영문 약어", match.english_abbr, true],
    ["동의어", (match.synonyms || []).join(", ")],
  ]);
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

function renderWordSuggestionCard(mcpState) {
  const sug = mcpState.word_suggestion;
  if (!sug) return "";
  if (sug.ambiguous && (sug.options || []).length) {
    return `<div class="question-card"><strong>확인이 필요합니다</strong>${escapeHtml(sug.question || "")}</div>`;
  }
  if (sug.existing_word_match) {
    return summaryCard([
      ["기존 단어", sug.existing_word_match, true],
      ["재사용 사유", sug.match_reason],
    ]);
  }
  if (sug.name && sug.english_abbr) {
    return `<div class="definition-card"><p><strong class="mono">${escapeHtml(sug.name)}</strong> (${escapeHtml(sug.english_abbr)})${sug.is_format_word ? ' · 형식단어' : ""}</p>
      <p>${escapeHtml(sug.definition || "")}</p>${sug.rationale ? `<div class="cell-note">${escapeHtml(sug.rationale)}</div>` : ""}</div>`;
  }
  return "";
}

function renderWordAbbreviationCard(mcpState) {
  const payload = mcpState.word_registration_payload;
  if (!payload || !payload.english_abbr) return "";
  return `<div class="abbr-card"><div class="abbr-code">${escapeHtml(payload.english_abbr)}</div>
    <div class="abbr-rationale">${escapeHtml(payload.word_name || "")} · ${escapeHtml(payload.definition || "")}</div></div>`;
}

function renderWordResultCard(mcpState) {
  if (mcpState.resolved_word) {
    return summaryCard([["재사용한 단어", mcpState.resolved_word.name, true]], "summary-card-ok");
  }
  const reg = mcpState.word_registration;
  if (reg && reg.request_id) {
    return summaryCard([
      ["신청 ID", reg.request_id.slice(0, 8) + "…", true],
      ["단어명", reg.word_name, true],
      ["영문 약어", reg.english_abbr, true],
      ["상태", "검토 대기 (PENDING_REVIEW)"],
    ], "summary-card-ok");
  }
  const blocked = mcpState.word_prepare_error;
  if (blocked) return summaryCard([["실패 사유 코드", blocked.code, true]], "summary-card-fail");
  return "";
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
      return renderExistingTermCard(mcpState);
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
    case "awaiting_word_confirm":
      return renderWordSuggestionCard(mcpState);
    case "awaiting_word_abbreviation":
      return renderWordAbbreviationCard(mcpState);
    case "word_reused":
    case "word_submitted":
    case "word_registration_failed":
    case "word_request_blocked":
      return renderWordResultCard(mcpState);
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
      fetchCatalogFromBackend();
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
