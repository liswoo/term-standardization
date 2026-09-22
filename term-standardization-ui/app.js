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
let CHAT_USER = null; // set to the logged-in username by showApp() below, once requireAuth() resolves

// ── 로그인 / 세션 게이트 ────────────────────────────────────────
// 로그인 전엔 대시보드/챗봇 등 실제 데이터를 전혀 렌더링·조회하지 않는다(아래
// renderAll()/fetchCatalogFromBackend()의 무조건 호출을 showApp() 안으로 옮김).
// body.pre-auth가 CSS로 app-shell 자체를 숨기므로, 세션 확인 중엔 로딩 문구만
// 보이고 실패했을 때만 로그인 카드가 나타난다 - 대시보드가 잠깐이라도 보이는
// 깜빡임이 없다.
let CURRENT_USER_ROLE = null;

function showApp(user) {
  document.body.classList.remove("pre-auth");
  document.getElementById("current-user-avatar").textContent = (user.display_name || "-").slice(0, 1);
  document.getElementById("current-user-name").textContent = user.display_name;
  document.getElementById("current-user-team").textContent = user.team || "-";
  CURRENT_USER_ROLE = user.role;
  const isAdmin = user.role === "ADMIN";
  document.getElementById("current-user-admin-badge").hidden = !isAdmin;
  document.getElementById("dify-admin-row").hidden = !isAdmin;
  document.getElementById("members-row").hidden = !isAdmin;
  document.getElementById("llm-model-row").hidden = !isAdmin;
  CHAT_USER = user.username;
  renderAll();
  fetchCatalogFromBackend();
}

async function submitAuthForm(url, payload, errorEl) {
  errorEl.hidden = true;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      const err = new Error(data.error || `HTTP ${res.status}`);
      err.data = data;
      throw err;
    }
    return data;
  } catch (err) {
    errorEl.textContent = AUTH_ERROR_LABELS[err.data?.error] || err.message;
    errorEl.hidden = false;
    throw err;
  }
}

const AUTH_ERROR_LABELS = {
  INVALID_CREDENTIALS: "아이디 또는 비밀번호가 올바르지 않습니다.",
  ACCOUNT_NOT_ACTIVE: "계정이 아직 활성 상태가 아닙니다(관리자 승인 대기 중이거나 정지/반려된 계정입니다).",
  MISSING_FIELDS: "모든 항목을 입력해주세요.",
  PASSWORD_TOO_SHORT: "비밀번호는 8자 이상이어야 합니다.",
  USERNAME_TAKEN: "이미 사용 중인 아이디입니다.",
  CURRENT_PASSWORD_INCORRECT: "현재 비밀번호가 올바르지 않습니다.",
  CODE_ALREADY_EXISTS: "이미 존재하는 도메인명입니다.",
  PENDING_REQUEST_ALREADY_EXISTS: "이미 같은 이름으로 검토 대기 중인 신청이 있습니다.",
  CATALOG_CHANGED_RETRY: "처리 중 목록이 변경되었습니다. 다시 시도해주세요.",
  CATALOG_CHANGED_REVALIDATE: "처리 중 목록이 변경되었습니다. 다시 시도해주세요.",
  DOMAIN_CODE_ALREADY_EXISTS: "이미 존재하는 도메인명입니다.",
  INVALID_FIELDS: "입력 항목을 다시 확인해주세요.",
  // 용어/단어 간편 입력 폼(quick_registration.py/word_registration.py) 전용.
  GUIDELINE_VIOLATION: "용어명이 명명 규칙을 위반했습니다. 이름을 수정해주세요.",
  EXACT_MATCH: "이미 동일한 이름의 표준이 존재합니다.",
  SYNONYM_CONFLICT: "입력한 동의어가 이미 다른 표준 용어의 이름·동의어와 겹칩니다.",
  SAME_MEANING: "의미가 같은 기존 용어가 있습니다. 기존 용어를 사용해주세요.",
  ABBREVIATION_ALREADY_USED: "이미 사용 중인 영문 약어입니다.",
  CONFIRMATION_NOT_FOUND: "요청 처리 중 문제가 발생했습니다. 다시 시도해주세요.",
  CONFIRMATION_EXPIRED_OR_CANCELLED: "요청이 만료되었습니다. 다시 시도해주세요.",
};

document.getElementById("auth-tab-login").addEventListener("click", () => {
  document.getElementById("auth-tab-login").classList.add("is-active");
  document.getElementById("auth-tab-signup").classList.remove("is-active");
  document.getElementById("login-form").hidden = false;
  document.getElementById("signup-form").hidden = true;
});
document.getElementById("auth-tab-signup").addEventListener("click", () => {
  document.getElementById("auth-tab-signup").classList.add("is-active");
  document.getElementById("auth-tab-login").classList.remove("is-active");
  document.getElementById("signup-form").hidden = false;
  document.getElementById("login-form").hidden = true;
});

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("login-error");
  try {
    const data = await submitAuthForm("/admin/auth/login", {
      username: document.getElementById("login-username").value.trim(),
      password: document.getElementById("login-password").value,
    }, errorEl);
    showApp(data.user);
  } catch { /* error already shown by submitAuthForm */ }
});

document.getElementById("signup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("signup-error");
  const noticeEl = document.getElementById("signup-notice");
  noticeEl.hidden = true;
  try {
    await submitAuthForm("/admin/auth/signup", {
      username: document.getElementById("signup-username").value.trim(),
      password: document.getElementById("signup-password").value,
      display_name: document.getElementById("signup-display-name").value.trim(),
      team: document.getElementById("signup-team").value.trim(),
    }, errorEl);
    document.getElementById("signup-form").reset();
    noticeEl.hidden = false;
  } catch { /* error already shown by submitAuthForm */ }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  try { await fetch("/admin/auth/logout", { method: "POST" }); } catch { /* best-effort */ }
  window.location.reload();
});

document.getElementById("settings-btn").addEventListener("click", () => switchView("settings"));

document.getElementById("change-password-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("change-password-error");
  const noticeEl = document.getElementById("change-password-notice");
  noticeEl.hidden = true;
  try {
    await submitAuthForm("/admin/auth/change-password", {
      current_password: document.getElementById("current-password-input").value,
      new_password: document.getElementById("new-password-input").value,
    }, errorEl);
    document.getElementById("change-password-form").reset();
    noticeEl.hidden = false;
  } catch { /* error already shown by submitAuthForm */ }
});

(async function requireAuth() {
  try {
    const res = await fetch("/admin/auth/me");
    if (res.ok) {
      const data = await res.json();
      if (data.ok) { showApp(data.user); return; }
    }
  } catch { /* MCP server unreachable - fall through to login screen */ }
  document.getElementById("auth-loading").hidden = true;
  document.getElementById("auth-card").hidden = false;
})();

// 읽기 전용 목록조회 워크플로우(용어표준화-목록조회). 대화 상태가 필요 없는 단순 조회라
// LLM 분류 파이프라인을 타는 Chatflow 대신 1회성 /v1/workflows/run으로 분리했습니다.
const LIST_TERMS_API = "/v1/workflows/run";
const LIST_TERMS_KEY = "app-U0pwaq4eXx9buXrPLtrqoEF0";
const STATUS_LABELS = { APPROVED: "승인", PENDING_REVIEW: "검토중", REJECTED: "반려", ACTIVE: "사용중", WAITING_FOR_WORD_APPROVAL: "단어 승인 대기", WAITING_FOR_DOMAIN_APPROVAL: "도메인 승인 대기" };

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
  termsPage: { limit: 50, offset: 0, total: 0, q: "", status: "", domain: "" },
  wordsPage: { limit: 50, offset: 0, total: 0, q: "", status: "", isFormatWord: "" },
  catalogPage: { limit: 50, offset: 0, total: 0, q: "", status: "", kinds: ["TERM", "WORD", "DOMAIN"] },
  activity: [...MOCK_ACTIVITY],
  history: [],
  chatRegisteredCount: 0,
};

// ── 네비게이션 ──────────────────────────────────────────────────
const VIEW_META = {
  dashboard: { title: "대시보드", subtitle: "용어 표준화 현황을 한눈에 확인하세요" },
  catalog: { title: "표준 데이터 조회", subtitle: "용어·단어·도메인을 조회하고, 위 탭에서 바로 신청할 수 있습니다" },
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
  if (view === "settings") {
    refreshLlmStatus();
  }
  if (view === "catalog" && catalogActiveTab === "browse") {
    fetchUnifiedCatalog();
  }
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

// ── 표준 데이터 조회 화면의 상단 탭(조회/용어 신청/단어 신청/도메인 신청) ──────
// 별도 화면 전환이 아니라 같은 view-catalog 안에서 패널만 바꾼다 - "조회"는 항상
// 최신 데이터를 보여줘야 하므로 그 탭으로 돌아올 때마다 다시 불러오고, 신청
// 탭들은 옵션(도메인 목록 등)을 처음 열 때만 지연 로드한다.
let catalogActiveTab = "browse";
function switchCatalogTab(tab) {
  catalogActiveTab = tab;
  document.querySelectorAll(".catalog-tab-btn").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.catalogTab === tab);
  });
  document.querySelectorAll(".catalog-tab-panel").forEach((panel) => {
    panel.hidden = panel.id !== `catalog-tab-${tab}`;
  });
  if (tab === "browse") fetchUnifiedCatalog();
  if (tab === "term-req") populateTermDomainOptions();
  if (tab === "domain-req") populateDomainRequestOptions();
}
document.querySelectorAll(".catalog-tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchCatalogTab(btn.dataset.catalogTab));
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

// terms/words/catalog 공통 페이지네이션 렌더링 - 이전/다음 버튼과 "n건 중 a-b" 라벨.
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

// 개인정보로 지정된 도메인의 (가상) 운영 데이터 샘플을 보여준다 - 매핑이 없으면
// 빈 배열이 오므로 그 경우 안내 문구만 표시한다.
async function showDomainSampleData(btn) {
  const code = btn.dataset.domainCode;
  const list = btn.nextElementSibling;
  btn.disabled = true;
  try {
    const res = await fetch(`/admin/domains/${encodeURIComponent(code)}/sample-data`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "조회 실패");
    if (!data.results.length) {
      list.innerHTML = `<li class="muted">매핑된 운영 데이터가 없습니다.</li>`;
    } else {
      list.innerHTML = data.results
        .map((r) => `<li><strong>${escapeHtml(r.table_name)}.${escapeHtml(r.column_name)}</strong>: ${r.sample.map(escapeHtml).join(", ") || "-"}</li>`)
        .join("");
    }
    list.hidden = false;
  } catch (err) {
    list.innerHTML = `<li class="muted">샘플 데이터를 불러오지 못했습니다: ${escapeHtml(err.message)}</li>`;
    list.hidden = false;
  } finally {
    btn.disabled = false;
  }
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
  document.getElementById("domain-bars-view-all")?.addEventListener("click", () => switchView("catalog"));
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
  renderDomainBars();
  renderActivity();
  renderHistory();
  // total은 실제 백엔드 total_count(전체 카탈로그 건수) - 화면에 그려진 현재
  // 페이지 행 수(state.terms.length)와는 다르다. 백엔드 조회 전(목업 데이터
  // 표시 중)에는 total이 아직 0이라 페이지 길이로 대체한다.
  document.getElementById("stat-total-terms").textContent =
    (state.termsPage.total || state.terms.length).toLocaleString();
  // "관리 도메인" 통계는 실제 전체 활성 도메인 수(state.domains, 백엔드 응답 전엔 0).
  const domainCountEl = document.getElementById("stat-domain-count");
  if (domainCountEl) domainCountEl.textContent = state.domains.length.toLocaleString();
  const pendingEl = document.getElementById("stat-pending-review");
  if (pendingEl) pendingEl.textContent = state.terms.filter((t) => t.status === "검토중").length;
}
// renderAll()의 최초 호출은 showApp()(로그인 성공 후)에서만 일어난다 - 로그인 전엔
// 목업 데이터조차 그리지 않는다.

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
    requester: t.requester || "",
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
    requester: w.requester || "",
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
//
// 필터를 연달아 빠르게 바꾸면 여러 요청이 동시에 떠 있을 수 있고, 네트워크
// 타이밍에 따라 먼저 보낸(오래된 필터 조건) 요청의 응답이 나중에 도착해 최신
// 상태를 덮어쓸 수 있다 - fetchToken으로 "가장 최근에 보낸 요청"만 반영하고
// 그보다 오래된 응답은 조용히 버린다.
let fetchToken = 0;
async function fetchCatalogFromBackend() {
  const myToken = ++fetchToken;
  try {
    const res = await fetch(LIST_TERMS_API, {
      method: "POST",
      headers: { Authorization: `Bearer ${LIST_TERMS_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        inputs: {
          limit: state.termsPage.limit, offset: state.termsPage.offset, q: state.termsPage.q,
          status: state.termsPage.status, domain: state.termsPage.domain, requester: "",
          words_limit: state.wordsPage.limit, words_offset: state.wordsPage.offset, words_q: state.wordsPage.q,
          words_status: state.wordsPage.status, words_requester: "",
          words_is_format_word: state.wordsPage.isFormatWord,
        },
        response_mode: "blocking", user: CHAT_USER,
      }),
    });
    if (!res.ok) throw new Error(`목록 조회 실패 (${res.status})`);
    if (myToken !== fetchToken) return; // 이 사이 더 최신 요청이 나갔으면 이 응답은 버린다.
    const payload = await res.json();
    if (myToken !== fetchToken) return; // json() 파싱 대기 중에도 더 최신 요청이 나갔을 수 있다.
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
      populateDomainFilterOptions();
    }
    state.activity = activityFromTerms(state.terms);
    renderAll();
  } catch (err) {
    console.warn("실제 백엔드에서 카탈로그를 불러오지 못해 데모 데이터를 유지합니다:", err);
  }
}
// 최초 호출은 showApp()(로그인 성공 후)에서만 일어난다.

// ── 표준 데이터 조회 (용어/단어/도메인 통합 화면) ──────────────────────
// /admin/standard-data(term_service/unified_catalog.py)를 통해 세 타입을 kind로
// 태그된 하나의 정렬/페이지 피드로 받는다. fetchCatalogFromBackend()와는 별개 경로 -
// 대시보드는 계속 그 워크플로를 그대로 쓴다.
const KIND_LABELS = { TERM: "용어", WORD: "단어", DOMAIN: "도메인" };
const KIND_COLORS = { TERM: "#2563eb", WORD: "#059669", DOMAIN: "#d97706" };

let catalogFetchToken = 0;
async function fetchUnifiedCatalog() {
  const myToken = ++catalogFetchToken;
  const p = state.catalogPage;
  const params = new URLSearchParams({
    kinds: p.kinds.join(","), q: p.q, status: p.status,
    limit: p.limit, offset: p.offset,
  });
  try {
    const res = await fetch(`/admin/standard-data?${params}`);
    const data = await res.json();
    if (myToken !== catalogFetchToken) return;
    if (!data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    state.catalogPage.total = data.total_count;
    renderCatalogTable(data.items);
    renderPagination("catalog-pagination", state.catalogPage, () => changeCatalogPage(-1), () => changeCatalogPage(1));
  } catch (err) {
    console.warn("표준 데이터 조회 실패:", err);
  }
}

function changeCatalogPage(delta) {
  state.catalogPage.offset = Math.max(0, state.catalogPage.offset + delta * state.catalogPage.limit);
  fetchUnifiedCatalog();
}

// 정부 원본 xlsx에 있었지만 한동안 비어 있던 필드들(2026-09-18) - 대부분의 행엔
// 값이 없으므로(원본 기준 허용값 38%, 표현형식 오버라이드 0.5%, 행정표준코드명
// 0.6%, 소관기관명 2%) 표에 항상 컬럼을 추가하는 대신 값이 있을 때만 "내용" 칸
// 아래 작은 보조줄로 보여준다. valid_values/display_format은 TERM 행에서 이미
// unified_catalog.py가 소속 도메인 값으로 대체(COALESCE)해서 내려주므로, 용어든
// 도메인이든 이 노트에 뜨는 값은 항상 "적용되는" 값이다. storage_format/data_type/
// unit/데이터길이는 도메인 고유 속성이라 TERM 행에도 소속 도메인 값을 그대로 조인해줌.
const EXTRA_FIELD_LABELS = {
  data_type: "데이터유형", valid_values: "허용값", display_format: "표현형식",
  storage_format: "저장형식", unit: "단위",
  administrative_code_name: "행정표준코드명", competent_agency: "소관기관명",
};
function catalogExtraFieldsNote(r) {
  const parts = Object.entries(EXTRA_FIELD_LABELS)
    .filter(([key]) => r[key])
    .map(([key, label]) => `${label}: ${escapeHtml(r[key])}`);
  if (r.data_length !== null && r.data_length !== undefined) {
    parts.splice(1, 0, `데이터길이: ${escapeHtml([r.data_length, r.decimal_length].filter((v) => v !== null && v !== undefined).join(","))}`);
  }
  return parts.length ? `<div class="cell-note">${parts.join(" · ")}</div>` : "";
}

function renderCatalogTable(items) {
  const tbody = document.getElementById("catalog-tbody");
  if (!tbody) return;
  tbody.innerHTML = items.length ? items.map((r) => `
    <tr>
      <td><span class="kind-badge" style="--kind-color:${KIND_COLORS[r.kind]}">${KIND_LABELS[r.kind] || r.kind}</span></td>
      <td><strong>${escapeHtml(r.logical_name)}</strong></td>
      <td><span class="mono">${escapeHtml(r.physical_name || "-")}</span></td>
      <td class="cell-def">${escapeHtml(r.content || "-")}${catalogExtraFieldsNote(r)}</td>
      <td>${r.domain ? `<span class="domain-tag" style="--tag-color:${domainColor(r.domain)}">${escapeHtml(r.domain)}</span>` : "-"}</td>
      <td><span class="status-badge status-${r.status === "APPROVED" ? "ok" : "pending"}">${STATUS_LABELS[r.status] || r.status}</span></td>
      <td class="muted">${escapeHtml(r.requester || "-")}</td>
      <td class="muted">${(r.created_at || "").slice(0, 10)}</td>
      <td>${r.kind === "DOMAIN" && r.status === "APPROVED" && r.is_personal_info
        ? `<button type="button" class="btn-ghost domain-sample-btn" data-domain-code="${escapeHtml(r.id)}">샘플 데이터 보기</button><ul class="domain-sample-list" hidden></ul>`
        : ""}</td>
    </tr>`).join("") : `<tr><td colspan="9" class="empty-state">조회된 데이터가 없습니다.</td></tr>`;
  const pill = document.getElementById("catalog-count-pill");
  if (pill) pill.textContent = `${(state.catalogPage.total || items.length).toLocaleString()}건`;
  tbody.querySelectorAll(".domain-sample-btn").forEach((btn) => btn.addEventListener("click", () => showDomainSampleData(btn)));
}

// 용어사전의 도메인 필터 <select>를 실제 도메인 목록(state.domains, 126건)으로
// 채운다 - 재조회 때마다 다시 그려도 현재 선택값은 유지한다.
//
// 도메인 설명 중엔 100자 넘는 것도 있다(예: 신용카드번호 BIN 규칙 전체 나열) -
// <select>는 옵션 텍스트 길이에 맞춰 스스로 넓어지는 브라우저가 많아서, 그걸
// 그대로 넣으면 선택하자마자 페이지 전체가 가로로 밀려버린다. 그래서 라벨
// 자체를 짧게 자르고, 잘리지 않은 전체 설명은 title 속성(마우스 오버 툴팁)
// 로만 보여준다 - CSS의 text-overflow:ellipsis만으로는 브라우저마다 select
// 렌더링이 달라 믿을 수 없어서, 문자열 자체를 짧게 만드는 쪽이 확실하다.
const DOMAIN_OPTION_LABEL_MAX = 40;
function truncateLabel(text, max = DOMAIN_OPTION_LABEL_MAX) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
let domainFilterPopulated = false;
function populateDomainFilterOptions() {
  const select = document.getElementById("terms-filter-domain");
  if (!select || domainFilterPopulated || !state.domains.length) return;
  domainFilterPopulated = true;
  const current = select.value;
  const options = [...state.domains]
    .sort((a, b) => a.code.localeCompare(b.code))
    .map((d) => {
      const full = `${d.code}${d.description ? ` - ${d.description}` : ""}`;
      return `<option value="${escapeHtml(d.code)}" title="${escapeHtml(full)}">${escapeHtml(truncateLabel(full))}</option>`;
    })
    .join("");
  select.innerHTML = `<option value="">도메인: 전체</option>${options}`;
  select.value = current;
}

// 용어사전/단어사전 필터 컨트롤 - select는 즉시, 통합 검색(이름·정의·요청자)은
// 300ms 디바운스로 반영하고 매번 offset을 0으로 되돌려 페이지가 꼬이지 않게 한다.
function bindFilterControls(page, ids, onChange) {
  const statusEl = document.getElementById(ids.status);
  const searchEl = document.getElementById(ids.search);
  const extraEl = ids.extra ? document.getElementById(ids.extra) : null;
  statusEl?.addEventListener("change", () => {
    page.status = statusEl.value;
    page.offset = 0;
    onChange();
  });
  extraEl?.addEventListener("change", () => {
    if (ids.extraKey) page[ids.extraKey] = extraEl.value;
    page.offset = 0;
    onChange();
  });
  let timer = null;
  searchEl?.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      page.q = searchEl.value.trim();
      page.offset = 0;
      onChange();
    }, 300);
  });
}
["term", "word", "domain"].forEach((k) => {
  document.getElementById(`catalog-kind-${k}`).addEventListener("change", () => {
    state.catalogPage.kinds = ["term", "word", "domain"]
      .filter((x) => document.getElementById(`catalog-kind-${x}`).checked)
      .map((x) => x.toUpperCase());
    state.catalogPage.offset = 0;
    fetchUnifiedCatalog();
  });
});
bindFilterControls(state.catalogPage,
  { status: "catalog-filter-status", search: "catalog-filter-search" },
  fetchUnifiedCatalog);

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
document.getElementById("open-dify-studio-btn").addEventListener("click", openDifyStudio);

// ── 회원 관리 바로가기 (새 창) ────────────────────────────────────
// 회원 관리는 별도 화면(members.html)에서 처리한다 - 같은 로그인 세션 쿠키를
// 공유하므로 별도 인증 없이 그대로 열리지만, 관리자가 아니면 members.html
// 자체가 접근을 막는다(showApp()에서 이 버튼 자체도 관리자가 아니면 숨김).
document.getElementById("open-members-btn").addEventListener("click", () => {
  window.open("members.html", "datave-members", "noopener,width=1040,height=760");
});

// ── LLM 모델 전환 (설정 화면) ────────────────────────────────────
// MCP 서버(term_service/admin_api.py)의 /admin/* 라우트를 Caddy가 이 오리진의
// 상대경로로 그대로 프록시합니다(tools/Caddyfile) - 위 /v1/* 프록시와 같은 이유.
const LLM_SWITCH_BUTTONS = {
  openai: document.getElementById("llm-switch-openai"),
  local: document.getElementById("llm-switch-local"),
};
const llmStatusDot = document.getElementById("llm-status-dot");

function setLlmSwitchButtonsDisabled(disabled) {
  Object.values(LLM_SWITCH_BUTTONS).forEach((btn) => {
    if (btn) btn.disabled = disabled;
  });
}

function renderLlmProvider(provider, configured) {
  Object.entries(LLM_SWITCH_BUTTONS).forEach(([key, btn]) => {
    if (btn) btn.classList.toggle("is-active", key === provider);
  });
  if (!llmStatusDot) return;
  if (configured) {
    llmStatusDot.textContent = provider === "local" ? "● 로컬 Qwen3 설정됨" : "● OpenAI 설정됨";
    llmStatusDot.className = "status-dot status-ok";
  } else {
    llmStatusDot.textContent = "● 설정 안 됨";
    llmStatusDot.className = "status-dot status-error";
  }
}

async function refreshLlmStatus() {
  try {
    const res = await fetch("/admin/llm-status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderLlmProvider(data.provider, data.configured);
  } catch {
    if (llmStatusDot) {
      llmStatusDot.textContent = "● 확인 실패 (MCP 서버 8100 확인)";
      llmStatusDot.className = "status-dot status-error";
    }
  }
}

async function switchLlmProvider(provider) {
  setLlmSwitchButtonsDisabled(true);
  if (llmStatusDot) {
    llmStatusDot.textContent = "● 전환 중... (챗플로우 재배포, 10~20초)";
    llmStatusDot.className = "status-dot";
  }
  try {
    const res = await fetch("/admin/llm-provider", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    renderLlmProvider(data.provider, data.configured);
  } catch (err) {
    if (llmStatusDot) {
      llmStatusDot.textContent = `● 전환 실패: ${err.message}`;
      llmStatusDot.className = "status-dot status-error";
    }
  } finally {
    setLlmSwitchButtonsDisabled(false);
  }
}

Object.entries(LLM_SWITCH_BUTTONS).forEach(([key, btn]) => {
  if (btn) btn.addEventListener("click", () => switchLlmProvider(key));
});

// 회원 관리 화면은 members.html로 분리되었다(관리자 전용, 새 창) - 그 파일이
// 자신의 인증/렌더링 로직을 독립적으로 갖고 있다.

// ── 도메인 신청 (표준 데이터 조회의 "도메인 신청" 탭, 버튼 기반 직접 입력 폼) ──
// 용어/단어 신청과 달리 대화가 아니라 폼 제출 한 번으로 끝나므로, 별도의
// prepare/confirm 두 턴을 프론트에서 흉내낼 필요가 없다 - /admin/domain-requests
// POST 한 번이 서버 쪽에서 이어서 처리한다.
// 신청 목록 자체는 여기서 따로 안 보여준다 - "조회" 탭이 검토 대기 신청까지
// 이미 병합해서 보여주므로 중복 방지.
let domainRequestOptionsLoaded = false;
async function populateDomainRequestOptions() {
  if (domainRequestOptionsLoaded) return;
  domainRequestOptionsLoaded = true;
  try {
    const res = await fetch("/admin/domain-requests/options");
    const data = await res.json();
    if (data.ok) {
      document.getElementById("dr-domain-group-options").innerHTML =
        data.domain_groups.map((g) => `<option value="${escapeHtml(g)}"></option>`).join("");
      document.getElementById("dr-data-type-options").innerHTML =
        data.data_types.map((t) => `<option value="${escapeHtml(t)}"></option>`).join("");
    }
  } catch { /* datalist는 없어도 입력 자체는 가능하므로 조용히 무시 */ }
  try {
    const res = await fetch("/admin/mock-tables");
    const data = await res.json();
    if (data.ok) {
      window.MOCKOPS_TABLES = data.tables;
      const tableSelect = document.getElementById("dr-mapping-table");
      tableSelect.innerHTML = `<option value="">선택 안 함</option>` +
        Object.keys(data.tables).map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
    }
  } catch { /* 매핑은 선택 사항이므로 조용히 무시 */ }
}

function updateMappingColumnOptions() {
  const table = document.getElementById("dr-mapping-table").value;
  const columnSelect = document.getElementById("dr-mapping-column");
  const columns = (window.MOCKOPS_TABLES && window.MOCKOPS_TABLES[table]) || [];
  columnSelect.innerHTML = `<option value="">선택 안 함</option>` +
    columns.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
}
document.getElementById("dr-mapping-table").addEventListener("change", updateMappingColumnOptions);

function toggleDrField(checkboxId, ...fieldIds) {
  const checked = document.getElementById(checkboxId).checked;
  fieldIds.forEach((id) => { document.getElementById(id).disabled = !checked; });
}
document.getElementById("dr-is-personal-info").addEventListener("change", () =>
  toggleDrField("dr-is-personal-info", "dr-personal-info-type", "dr-protection-level", "dr-mapping-table", "dr-mapping-column"));
document.getElementById("dr-is-encrypted").addEventListener("change", () =>
  toggleDrField("dr-is-encrypted", "dr-encryption-method"));

document.getElementById("domain-request-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("domain-request-error");
  const noticeEl = document.getElementById("domain-request-notice");
  noticeEl.hidden = true;
  const numOrNull = (id) => { const v = document.getElementById(id).value; return v === "" ? null : Number(v); };
  const payload = {
    code: document.getElementById("dr-code").value.trim(),
    domain_group: document.getElementById("dr-domain-group").value.trim(),
    physical_name: document.getElementById("dr-physical-name").value.trim(),
    data_type: document.getElementById("dr-data-type").value.trim(),
    data_length: numOrNull("dr-data-length"),
    decimal_length: numOrNull("dr-decimal-length"),
    min_value: document.getElementById("dr-min-value").value.trim(),
    max_value: document.getElementById("dr-max-value").value.trim(),
    display_format: document.getElementById("dr-display-format").value.trim(),
    source_classification: document.getElementById("dr-source-classification").value.trim(),
    valid_values: document.getElementById("dr-valid-values").value.trim(),
    default_value: document.getElementById("dr-default-value").value.trim(),
    description: document.getElementById("dr-description").value.trim(),
    request_reason: document.getElementById("dr-request-reason").value.trim(),
    is_personal_info: document.getElementById("dr-is-personal-info").checked,
    personal_info_type: document.getElementById("dr-personal-info-type").value.trim(),
    protection_level: document.getElementById("dr-protection-level").value.trim(),
    is_encrypted: document.getElementById("dr-is-encrypted").checked,
    encryption_method: document.getElementById("dr-encryption-method").value.trim(),
    mapping_table: document.getElementById("dr-mapping-table").value,
    mapping_column: document.getElementById("dr-mapping-column").value,
  };
  try {
    await submitAuthForm("/admin/domain-requests", payload, errorEl);
    document.getElementById("domain-request-form").reset();
    updateMappingColumnOptions();
    toggleDrField("dr-is-personal-info", "dr-personal-info-type", "dr-protection-level", "dr-mapping-table", "dr-mapping-column");
    toggleDrField("dr-is-encrypted", "dr-encryption-method");
    noticeEl.hidden = false;
    fetchUnifiedCatalog();
  } catch { /* 에러는 submitAuthForm이 이미 표시함 */ }
});

// ── 용어/단어 신청 (표준 데이터 조회의 "용어 신청"/"단어 신청" 탭) ──────────
// 간편 입력 - 폼 한 번 제출로 끝나되 /admin/term-requests·/admin/word-requests가
// registration.py/word_registration.py의 prepare()/submit()을 그대로 태우므로 챗봇과 동일한
// 품질 검증(용어는 임베딩+LLM 의미비교까지)을 거친다 - 단, 다단계 안내 없이 실패 사유를 한 번에
// 에러로 보여줌. 단어 신청 탭은 추가로 "AI와 대화하며 등록"(기존 플로팅 챗봇 재사용) 진입점이
// 있다. 용어 신청 탭은 그 진입점을 없앴다(2026-09-21) - 헤더의 "신규 용어 등록" 버튼과 같은
// 챗봇을 여는 중복 기능이라서 - 대신 이 탭 안의 AI 추천을 ON/OFF 하는 토글이 있다(아래).
document.getElementById("word-ai-start-btn").addEventListener("click", () => {
  openChat();
  submitChatMessage("단어를 등록할래요");
});

let termDomainOptionsLoaded = false;
function populateTermDomainOptions() {
  const list = document.getElementById("tr-domain-options");
  if (!list || termDomainOptionsLoaded || !state.domains.length) return;
  termDomainOptionsLoaded = true;
  list.innerHTML = [...state.domains]
    .sort((a, b) => a.code.localeCompare(b.code))
    .map((d) => `<option value="${escapeHtml(d.code)}">${escapeHtml(d.description || "")}</option>`)
    .join("");
}

// 도메인 하나의 상세(허용값/표현형식/저장형식 등)를 가져온다 - list_data_domains()
// (state.domains, 목록조회 워크플로우 경유)는 이 필드들을 안 담고 있어서 별도 REST 호출이
// 필요하다. 용어 신청 폼의 도메인 참고값 자동표시와 챗봇 등록완료 카드 둘 다 이 함수를 씀.
async function fetchDomainDetail(code) {
  if (!code) return null;
  try {
    const res = await fetch(`/admin/domains/${encodeURIComponent(code)}`);
    const data = await res.json();
    return data.ok ? data.domain : null;
  } catch {
    return null;
  }
}

// "도메인이 결정하는" 값(허용값/표현형식/저장형식)은 신청자가 입력하지 않고, 도메인을
// 고르면 참고용으로만 자동 표시한다(2026-09-18) - 제출 payload에는 포함되지 않음.
let termDomainDerivedFetchToken = 0;
async function populateTermDomainDerivedFields() {
  const code = document.getElementById("tr-domain").value.trim();
  const wrap = document.getElementById("tr-domain-derived");
  const myToken = ++termDomainDerivedFetchToken;
  const domain = await fetchDomainDetail(code);
  if (myToken !== termDomainDerivedFetchToken) return;
  if (!domain) {
    wrap.hidden = true;
    return;
  }
  document.getElementById("tr-valid-values").value = domain.valid_values || "-";
  document.getElementById("tr-display-format").value = domain.display_format || "-";
  document.getElementById("tr-storage-format").value = domain.storage_format || "-";
  wrap.hidden = false;
}
let termDomainDerivedTimer = null;
document.getElementById("tr-domain").addEventListener("input", () => {
  clearTimeout(termDomainDerivedTimer);
  termDomainDerivedTimer = setTimeout(populateTermDomainDerivedFields, 300);
});

// ── 용어 신청 간편 입력: 챗봇처럼 즉시 반응하는 이름 확인 + 정의/도메인/약어 추천 ──
// (2026-09-21) 제출 전에는 몰랐던 것들(이미 있는 이름인지, 정의/도메인/약어 초안)을
// 필드를 벗어나는 즉시 알려준다. 전부 기존 챗봇/제출 경로가 쓰는 로직을 그대로 재사용하는
// 읽기전용 라우트라, "이미 있다/없다"는 여기서 바로 답하지만 의미 기반 중복 판정(SAME_
// MEANING)처럼 더 깊은 판단은 여전히 제출 시점에만 실행된다(느리고 부작용 있는 registration.
// prepare()를 여기서 또 돌리지 않음).
// AI 추천 ON/OFF(2026-09-21). 기본 ON, 새로고침하면 다시 ON(저장하지 않음). OFF면 아래의
// 즉시 반응(이름 확인/정의 추천/도메인·약어 추천)을 전부 호출하지 않고, 대신 "간편 입력으로 신청"
// 시점에 안 되는 칸을 빨간 테두리로 알려준다(제출 검증은 ON/OFF와 무관하게 항상 동작).
let termAiAssist = true;
let termNameStatus = ""; // "" | "checking" | "available" | "invalid" | "exact_match" | "synonym_match" | "pending"
let termNameCheckToken = 0;

function setFieldState(inputEl, hintEl, kind, message) {
  inputEl.classList.remove("field-valid", "field-invalid");
  if (kind === "ok") inputEl.classList.add("field-valid");
  else if (kind === "error") inputEl.classList.add("field-invalid");
  if (hintEl) {
    hintEl.classList.remove("field-hint-ok", "field-hint-error");
    if (message) {
      hintEl.textContent = message;
      hintEl.classList.add(kind === "error" ? "field-hint-error" : "field-hint-ok");
      hintEl.hidden = false;
    } else {
      hintEl.hidden = true;
    }
  }
}

async function checkTermName() {
  if (!termAiAssist) return;
  const input = document.getElementById("tr-term-name");
  const hint = document.getElementById("tr-term-name-hint");
  const termName = input.value.trim();
  const myToken = ++termNameCheckToken;
  if (!termName) {
    termNameStatus = "";
    setFieldState(input, hint, "", "");
    return;
  }
  let data;
  try {
    const res = await fetch(`/admin/term-requests/check-name?term_name=${encodeURIComponent(termName)}`);
    data = await res.json();
  } catch {
    return; // 네트워크 오류는 조용히 무시 - 제출 시점에 어차피 다시 검증된다.
  }
  if (myToken !== termNameCheckToken || input.value.trim() !== termName) return; // 그새 값이 바뀜 - 낡은 응답 폐기.
  if (!data.ok || data.status === "empty") {
    termNameStatus = "";
    setFieldState(input, hint, "", "");
    return;
  }
  termNameStatus = data.status;
  if (data.status === "available") {
    setFieldState(input, hint, "ok", data.message);
    suggestDefinitionForTerm(termName);
  } else {
    setFieldState(input, hint, "error", data.message);
    document.getElementById("tr-definition-suggestion").hidden = true;
  }
}
document.getElementById("tr-term-name").addEventListener("blur", checkTermName);
document.getElementById("tr-term-name").addEventListener("input", () => {
  // 값이 바뀌는 순간 이전 판정은 더 이상 유효하지 않음 - blur가 다시 돌 때까지 중립 상태로.
  termNameStatus = "";
  setFieldState(document.getElementById("tr-term-name"), document.getElementById("tr-term-name-hint"), "", "");
});

let termDefinitionSuggestToken = 0;
// history: 지금까지의 {question,answer} 목록(챗봇의 definition_clarification_history와
// 동형) - 후보 라벨을 고르는 건 "이 의미가 맞다"는 답일 뿐 완성된 정의 문장이 아니므로,
// 클릭해도 바로 적용하지 않고 그 답까지 반영해서 다시 추천을 받는다(서버가 진짜 정의
// 문장을 새로 써서 돌려줌 - suggest_definition()의 clarification_history 경로 재사용).
async function suggestDefinitionForTerm(termName, history) {
  history = history || [];
  const wrap = document.getElementById("tr-definition-suggestion");
  const myToken = ++termDefinitionSuggestToken;
  let data;
  try {
    const params = new URLSearchParams({ term_name: termName });
    if (history.length) params.set("clarification_history", JSON.stringify(history));
    const res = await fetch(`/admin/term-requests/suggest-definition?${params.toString()}`);
    data = await res.json();
  } catch {
    return;
  }
  if (myToken !== termDefinitionSuggestToken || termNameStatus !== "available") return;
  if (!data.ok) { wrap.hidden = true; return; }
  if (data.ambiguous && (data.options || []).length) {
    wrap.innerHTML = `<p class="field-suggestion-question">${escapeHtml(data.question || "정의가 명확하지 않습니다 - 아래 중 선택하거나 직접 작성하세요.")}</p>
      <div class="field-suggestion-options">${data.options.map((o) => `<button type="button" class="btn-ghost field-option-btn">${escapeHtml(o)}</button>`).join("")}</div>`;
    wrap.querySelectorAll(".field-option-btn").forEach((btn, i) => {
      btn.addEventListener("click", () => {
        suggestDefinitionForTerm(termName, [...history, { question: data.question, answer: data.options[i] }]);
      });
    });
    wrap.hidden = false;
  } else if (data.definition) {
    if (history.length) {
      // 이미 한 번 이상 명확화 질문에 답한 뒤 나온 결과 - 사용자가 이미 선택으로 의사를
      // 표시했으니 한 번 더 클릭을 요구하지 않고 바로 반영한다.
      document.getElementById("tr-definition").value = data.definition;
      wrap.hidden = true;
      maybeSuggestFollowups();
    } else {
      wrap.innerHTML = `<button type="button" class="field-suggestion-chip"><strong>추천 정의 (클릭하여 적용)</strong><span>${escapeHtml(data.definition)}</span></button>`;
      wrap.querySelector(".field-suggestion-chip").addEventListener("click", () => {
        document.getElementById("tr-definition").value = data.definition;
        wrap.hidden = true;
        maybeSuggestFollowups();
      });
      wrap.hidden = false;
    }
  } else {
    wrap.hidden = true;
  }
}

// 용어명이 "사용 가능"으로 확인됐고 정의도 채워졌을 때만 도메인/약어를 추천한다 - 둘 다
// "일일이 묻지 않아도 진행 가능한 영역"(사용자 지시, 2026-09-21)이라 버튼 없이 바로 추천.
let termFollowupsToken = 0;
async function maybeSuggestFollowups() {
  if (!termAiAssist || termNameStatus !== "available") return;
  const termName = document.getElementById("tr-term-name").value.trim();
  const definition = document.getElementById("tr-definition").value.trim();
  if (!termName || !definition) return;
  const domainInput = document.getElementById("tr-domain");
  const abbrInput = document.getElementById("tr-english-abbr");
  const domainNote = document.getElementById("tr-domain-suggestion-note");
  const abbrNote = document.getElementById("tr-english-abbr-suggestion-note");
  const myToken = ++termFollowupsToken;
  let data;
  try {
    const res = await fetch(`/admin/term-requests/suggest-followups?term_name=${encodeURIComponent(termName)}&definition=${encodeURIComponent(definition)}`);
    data = await res.json();
  } catch {
    return;
  }
  if (myToken !== termFollowupsToken || !data.ok) return;
  const recommended = data.domain && data.domain.recommended_domain;
  if (recommended && !domainInput.value.trim()) {
    domainInput.value = recommended;
    const pct = Math.round((data.domain.confidence || 0) * 100);
    domainNote.textContent = `추천: ${recommended}(${data.domain.recommended_domain_description || "설명 없음"}) - 비교군 ${data.domain.sample_size || 0}건 중 ${pct}% 사용. 직접 입력해 바꿀 수 있습니다.`;
    domainNote.hidden = false;
    populateTermDomainDerivedFields();
  }
  const abbr = data.abbreviation && data.abbreviation.abbreviation;
  if (abbr && !abbrInput.value.trim()) {
    abbrInput.value = abbr;
    abbrNote.textContent = `추천: ${abbr} - ${data.abbreviation.rationale || ""}. 직접 입력해 바꿀 수 있습니다.`;
    abbrNote.hidden = false;
  }
}
document.getElementById("tr-definition").addEventListener("blur", maybeSuggestFollowups);

// ── 칸별 오류 표시(빨간 테두리 + 문구) ──
// 제출 시점에 "이 칸 때문에 신청이 안 된다"를 알려주는 용도. ON/OFF와 무관하게 항상 동작한다.
// (이름 칸은 ON일 때 blur 확인의 초록/빨강 표시와 같은 자리를 쓴다 - setFieldState 공용)
const TERM_FIELDS = {
  term_name: ["tr-term-name", "tr-term-name-hint"],
  definition: ["tr-definition", "tr-definition-hint"],
  domain: ["tr-domain", "tr-domain-hint"],
  synonyms: ["tr-synonyms", "tr-synonyms-hint"],
  english_abbr: ["tr-english-abbr", "tr-english-abbr-hint"],
};
function markTermFieldError(field, message) {
  const [inputId, hintId] = TERM_FIELDS[field];
  setFieldState(document.getElementById(inputId), document.getElementById(hintId), "error", message);
}
function clearTermFieldError(field) {
  const [inputId, hintId] = TERM_FIELDS[field];
  const input = document.getElementById(inputId);
  if (input.classList.contains("field-invalid")) setFieldState(input, document.getElementById(hintId), "", "");
}
// 값을 고치기 시작하면 그 칸의 빨간 표시는 더 이상 유효하지 않다(이름 칸은 위에 자체 리스너가 있음).
["definition", "domain", "synonyms", "english_abbr"].forEach((field) => {
  document.getElementById(TERM_FIELDS[field][0]).addEventListener("input", () => clearTermFieldError(field));
});

// 서버(quick_registration/registration)가 돌려주는 거부 코드 → 어느 칸 때문인지.
// 미등록 도메인은 서버가 거부하지 않고 경고만 붙여 접수하므로(UNREGISTERED_DOMAIN_REQUIRES_REVIEW)
// 여기에 없다 - 도메인 칸은 "비어 있음"만 실패로 본다. CATALOG_CHANGED_* 등 칸과 무관한 코드도 없음.
const TERM_ERROR_FIELDS = {
  GUIDELINE_VIOLATION: ["term_name"],
  EXACT_MATCH: ["term_name"],
  WORD_GAP_REQUIRES_REGISTRATION: ["term_name"],
  PENDING_REQUEST_ALREADY_EXISTS: ["term_name"],
  SAME_MEANING: ["term_name", "definition"],
  SYNONYM_CONFLICT: ["synonyms"],
  ABBREVIATION_ALREADY_USED: ["english_abbr"],
};

// 서버 왕복 전에 브라우저에서 바로 잡을 수 있는 것들(스키마 RegistrationInput의 길이 제한과 동일).
// form에 novalidate를 줘서 브라우저 기본 말풍선 대신 이 검증이 모든 칸을 한꺼번에 빨갛게 표시한다.
function validateTermForm(payload) {
  const problems = [];
  const name = payload.term_name, definition = payload.definition;
  if (!name) problems.push(["term_name", "용어명을 입력해주세요."]);
  else if (name.length < 2 || name.length > 20) problems.push(["term_name", "용어명은 2~20자로 입력해주세요."]);
  if (!definition) problems.push(["definition", "정의를 입력해주세요."]);
  else if (definition.length < 5) problems.push(["definition", "정의는 5자 이상 입력해주세요."]);
  else if (definition.length > 4000) problems.push(["definition", "정의는 4000자 이내로 입력해주세요."]);
  if (!payload.domain) problems.push(["domain", "도메인을 입력해주세요."]);
  // 동의어: 각 항목 1~100자, 최대 30개(RegistrationInput). 쉼표로 나눈 뒤 빈 항목은 이미 걸러져 있다.
  const synonyms = payload.synonyms;
  if (synonyms.length > 30) problems.push(["synonyms", "동의어는 최대 30개까지 입력할 수 있습니다."]);
  else if (synonyms.some((x) => x.length > 100)) problems.push(["synonyms", "동의어는 각각 100자 이내로 입력해주세요."]);
  return problems;
}

// 진행 중이던/표시 중이던 AI 추천 흔적만 걷어낸다(입력한 값은 그대로 둠) - 토글을 끌 때와
// 초기화 때 공용. 아직 도착 안 한 비동기 응답이 뒤늦게 칸을 채우지 못하도록 각 fetch 토큰과
// 디바운스 타이머도 같이 무효화한다.
function clearTermAiSuggestions() {
  termNameCheckToken++;
  termDefinitionSuggestToken++;
  termFollowupsToken++;
  termDomainDerivedFetchToken++;
  clearTimeout(termDomainDerivedTimer);
  termNameStatus = "";
  const nameInput = document.getElementById("tr-term-name");
  // 이름 칸의 빨강은 "이름 확인" 결과일 수도, 제출 거부 표시일 수도 있어 초록/빨강 상관없이 걷어낸다.
  setFieldState(nameInput, document.getElementById("tr-term-name-hint"), "", "");
  const suggestion = document.getElementById("tr-definition-suggestion");
  suggestion.innerHTML = "";
  suggestion.hidden = true;
  document.getElementById("tr-domain-suggestion-note").hidden = true;
  document.getElementById("tr-english-abbr-suggestion-note").hidden = true;
}

// 모든 칸과 추천/판정/오류 표시를 처음 상태로 되돌린다(초기화 버튼 + 제출 성공 후 공용).
// AI 추천 ON/OFF 선택은 유지한다 - 초기화는 "입력"을 비우는 것이지 사용자의 모드 선택이 아니다.
function resetTermRequestForm() {
  document.getElementById("term-request-form").reset();
  clearTermAiSuggestions();
  Object.keys(TERM_FIELDS).forEach(clearTermFieldError);
  document.getElementById("tr-domain-derived").hidden = true;
  document.getElementById("term-request-error").hidden = true;
  document.getElementById("term-request-notice").hidden = true;
}
document.getElementById("term-request-reset").addEventListener("click", resetTermRequestForm);

function setTermAiAssist(on) {
  termAiAssist = on;
  const toggle = document.getElementById("term-ai-toggle");
  toggle.classList.toggle("is-on", on);
  toggle.setAttribute("aria-checked", String(on));
  document.getElementById("term-ai-toggle-label").textContent = on ? "AI 추천 ON" : "AI 추천 OFF";
  if (!on) {
    clearTermAiSuggestions(); // 화면에 떠 있던 추천/판정과 진행 중이던 요청을 정리(입력값은 유지)
  } else if (document.getElementById("tr-term-name").value.trim()) {
    checkTermName(); // 이미 이름을 적어둔 채 켰다면 지금 값으로 바로 확인/추천을 시작
  }
}
document.getElementById("term-ai-toggle").addEventListener("click", () => setTermAiAssist(!termAiAssist));

document.getElementById("term-request-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("term-request-error");
  const noticeEl = document.getElementById("term-request-notice");
  const submitBtn = document.getElementById("term-request-submit");
  noticeEl.hidden = true;
  const payload = {
    term_name: document.getElementById("tr-term-name").value.trim(),
    definition: document.getElementById("tr-definition").value.trim(),
    domain: document.getElementById("tr-domain").value.trim(),
    synonyms: document.getElementById("tr-synonyms").value.split(",").map((s) => s.trim()).filter(Boolean),
    english_abbr: document.getElementById("tr-english-abbr").value.trim(),
    // 허용값/표현형식/저장형식은 선택한 도메인이 정하는 값이라 참고용 표시일 뿐 -
    // 제출 payload에는 포함하지 않는다(populateTermDomainDerivedFields 참고).
  };
  // 지난 제출의 빨간 표시를 먼저 걷어낸다(이름 칸의 ON 모드 초록 확인 표시는 건드리지 않음).
  Object.keys(TERM_FIELDS).forEach(clearTermFieldError);
  errorEl.hidden = true;

  const problems = validateTermForm(payload);
  if (problems.length) {
    problems.forEach(([field, message]) => markTermFieldError(field, message));
    errorEl.textContent = AUTH_ERROR_LABELS.INVALID_FIELDS;
    errorEl.hidden = false;
    // focus()는 쓰지 않는다 - 이름 칸에 focus→blur가 일어나면 ON 모드의 이름 확인이 다시 돌아
    // 방금 표시한 빨간 표시를 덮어쓸 수 있다. 스크롤만 첫 문제 칸으로 옮긴다.
    document.getElementById(TERM_FIELDS[problems[0][0]][0]).scrollIntoView({ block: "center", behavior: "smooth" });
    return;
  }

  // 임베딩+LLM 의미비교(registration.prepare)가 실행돼 도메인/단어보다 오래 걸릴 수 있다.
  submitBtn.disabled = true;
  submitBtn.textContent = "확인 중...";
  try {
    await submitAuthForm("/admin/term-requests", payload, errorEl);
    resetTermRequestForm();
    noticeEl.hidden = false;
    fetchUnifiedCatalog();
  } catch (err) {
    const code = err.data?.error;
    let message = AUTH_ERROR_LABELS[code] || err.message;
    if (code === "GUIDELINE_VIOLATION") {
      message = err.data.validation?.violations?.[0]?.reason || message;
    } else if (code === "WORD_GAP_REQUIRES_REGISTRATION" && err.data.message) {
      // 문구는 서버(quick_registration.word_gap_message)가 정한다 - 입력 중 이름 확인(check-name)이
      // 주는 문구와 같아서 두 시점에 같은 말이 나온다.
      message = err.data.message;
      errorEl.textContent = message;
      errorEl.hidden = false;
    }
    let fields = TERM_ERROR_FIELDS[code] || [];
    if (code === "INVALID_FIELDS" && Array.isArray(err.data.detail)) {
      // 브라우저 검증을 통과했는데 서버 스키마가 거부한 경우 - pydantic의 loc[0]이 칸 이름.
      fields = [...new Set(err.data.detail.map((d) => d.loc?.[0]).filter((f) => f in TERM_FIELDS))];
    }
    fields.forEach((field) => markTermFieldError(field, message));
    if (fields.length) {
      document.getElementById(TERM_FIELDS[fields[0]][0]).scrollIntoView({ block: "center", behavior: "smooth" });
    }
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "간편 입력으로 신청";
  }
});

document.getElementById("word-request-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("word-request-error");
  const noticeEl = document.getElementById("word-request-notice");
  noticeEl.hidden = true;
  const payload = {
    word_name: document.getElementById("wr-word-name").value.trim(),
    definition: document.getElementById("wr-definition").value.trim(),
    english_abbr: document.getElementById("wr-english-abbr").value.trim(),
    is_format_word: document.getElementById("wr-is-format-word").checked,
    domain_classification: document.getElementById("wr-domain-classification").value.trim(),
  };
  try {
    await submitAuthForm("/admin/word-requests", payload, errorEl);
    document.getElementById("word-request-form").reset();
    noticeEl.hidden = false;
    fetchUnifiedCatalog();
  } catch { /* 에러는 submitAuthForm이 이미 표시함 */ }
});

// ── 채팅 UI 헬퍼 ────────────────────────────────────────────────
const chatBody = document.getElementById("chat-body");
const CHAT_INITIAL_HTML = chatBody.innerHTML;

// 첫 인사말의 3개 버튼은 정적 HTML이라 클릭 리스너가 없습니다 - innerHTML을
// 다시 써넣을 때마다(최초 로드, 대화 초기화) 새로 바인딩해줘야 합니다.
function wireOpeningOptions() {
  chatBody.querySelectorAll("#opening-option-row .option-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      chatBody.querySelectorAll("#opening-option-row .option-chip").forEach((b) => (b.disabled = true));
      submitChatMessage(btn.dataset.value);
    });
  });
}
wireOpeningOptions();

// 여러 용어를 연달아 등록하다 보면 이전 대화의 상태(선택한 도메인, 추천받은
// 정의/약어 등)가 새 요청과 뒤섞여 엉뚱한 답변으로 이어질 수 있습니다 - 새
// Dify conversation_id로 완전히 새로 시작해서 그 가능성을 원천 차단합니다.
document.getElementById("chat-reset").addEventListener("click", () => {
  chatConversationId = null;
  chatBody.innerHTML = CHAT_INITIAL_HTML;
  wireOpeningOptions();
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

// A term's awaiting_definition already accepts free text as the definition verbatim
// (set_definition) - unlike a new word, which needed a real backend mode switch
// (edit_word_definition) since typing there re-triggers a whole new suggestion instead.
// So this button is purely a client-side nudge: no round trip, no value sent through
// classify at all - sending "내가 새로 정의할래요" itself through set_definition would
// register that literal phrase as the definition, which is exactly the bug this avoids.
function addWriteOwnDefinitionButton(bubbleWrap) {
  const row = document.createElement("div");
  row.className = "option-row";
  row.innerHTML = `<button type="button" class="option-chip">내가 새로 정의할래요</button>`;
  bubbleWrap.querySelector(".bubble").appendChild(row);
  row.querySelector(".option-chip").addEventListener("click", () => {
    row.querySelector(".option-chip").disabled = true;
    addBotBubble(escapeHtml("네, 정의를 직접 입력해 주세요."));
    chatInput.focus();
  });
  scrollChatToBottom();
}

// 결과/막힘 등 "끝난 지점"(터미널 스테이지)에서 다음 행동을 버튼으로 제시합니다.
// 두 버튼 모두 실제 서버 왕복을 거칩니다 - "사용/종료" 쪽을 로컬에서만 처리하도록
// 했다가, 서버 쪽 stage가 그 터미널 스테이지에 영영 멈춰 있게 되어 그 다음
// 무관한 메시지에도 이 stage의 카드/서술이 계속 재등장하는 버그로 이어진 적이
// 있습니다(실사용 중 재현됨). "여기서 마칠게요"는 이미 있는 restart 인텐트로
// 보내 상태를 실제로 awaiting_term_direct까지 초기화합니다. 전송값은 라벨과
// 무관하게 고정된 값들로만 보내서, 분류 LLM이 어떤 표현으로도 헷갈리지 않게
// 합니다(build_chatflow.py CLASSIFY_TERMINAL_RULE 참고).
const CONTINUE_TERM_VALUE = "다른 용어를 등록할래요";
const CONTINUE_WORD_VALUE = "다른 단어를 등록할래요";
const CLOSE_VALUE = "여기서 마칠게요";
// Same 3 phrases as the opening bubble's static buttons (index.html) - reused after
// "여기서 마칠게요" resets to idle, so the user gets the same fresh set of next-step
// options instead of a dead-end "알겠습니다" with nothing to click.
const OPENING_MENU_OPTIONS = [
  { label: "용어를 추천해주세요", value: "용어를 추천해주세요" },
  { label: "용어를 등록할래요", value: "용어를 등록할래요" },
  { label: "단어를 등록할래요", value: "단어를 등록할래요" },
];

function terminalActionsFor(mcpState) {
  if (!mcpState) return null;
  switch (mcpState.stage) {
    case "term_lookup_result":
      // Always "여기서 마칠게요", never "이 용어를 사용할게요" - up to 5 candidates are
      // shown here (search_terms_by_meaning's limit), so "이 용어" ("this term") is
      // ambiguous about which one, and the button's label must also match what the
      // click actually sends/displays as the user's own message (see CLOSE_VALUE) or
      // the two feel like a non sequitur back to back - reported live by the user.
      return [{ label: "새 용어를 등록할래요", value: CONTINUE_TERM_VALUE }, { label: "여기서 마칠게요", value: CLOSE_VALUE }];
    case "existing_term_found":
    case "definition_blocked":
      return [{ label: "새 용어를 등록할래요", value: CONTINUE_TERM_VALUE }, { label: "이 용어를 사용할게요", value: CLOSE_VALUE }];
    case "pending_request_found":
      return [{ label: "새 용어를 등록할래요", value: CONTINUE_TERM_VALUE }, { label: "알겠어요, 기다릴게요", value: CLOSE_VALUE }];
    case "cancelled":
    case "registration_failed":
      return [{ label: "새 용어를 등록할래요", value: CONTINUE_TERM_VALUE }, { label: "여기서 마칠게요", value: CLOSE_VALUE }];
    case "submitted":
      return [{ label: "새 용어도 등록할래요", value: CONTINUE_TERM_VALUE }, { label: "여기서 마칠게요", value: CLOSE_VALUE }];
    case "word_reused":
    case "word_submitted":
      return [{ label: "새 단어도 등록할래요", value: CONTINUE_WORD_VALUE }, { label: "여기서 마칠게요", value: CLOSE_VALUE }];
    case "word_registration_failed":
    case "word_request_blocked":
      return [{ label: "새 단어를 등록할래요", value: CONTINUE_WORD_VALUE }, { label: "여기서 마칠게요", value: CLOSE_VALUE }];
    case "domain_spec_unavailable":
    case "domain_request_blocked":
      return [{ label: "새 용어를 등록할래요", value: CONTINUE_TERM_VALUE }, { label: "여기서 마칠게요", value: CLOSE_VALUE }];
    default:
      return null;
  }
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

function renderDomainSuggestionCard(mcpState) {
  const sug = mcpState.domain_suggestion;
  if (!sug) return "";
  if (sug.ambiguous && (sug.options || []).length) {
    return `<div class="question-card"><strong>확인이 필요합니다</strong>${escapeHtml(sug.question || "")}</div>`;
  }
  if (sug.existing_domain_match) {
    return summaryCard([
      ["기존 도메인 코드", sug.existing_domain_match, true],
      ["재사용 사유", sug.match_reason],
    ]);
  }
  if (sug.code) {
    return summaryCard([
      ["도메인명(코드)", sug.code, true],
      ["도메인그룹", sug.domain_group],
      ["데이터유형", sug.data_type, true],
      ["길이", sug.data_length ?? "-", true],
      ["소수점", sug.decimal_length ?? "-", true],
      ["표현형식", sug.display_format],
      ["허용값", sug.valid_values],
      ["설명", sug.description],
      ["근거", sug.rationale],
    ]);
  }
  return "";
}

function renderDomainRequestBlockedCard(mcpState) {
  const blocked = mcpState.domain_prepare_error;
  if (!blocked) return "";
  return summaryCard([["실패 사유 코드", blocked.code, true]], "summary-card-fail");
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

const REGISTRATION_STATUS_LABEL = {
  PENDING_REVIEW: "검토 대기 (PENDING_REVIEW)",
  WAITING_FOR_WORD_APPROVAL: "단어 승인 대기 (WAITING_FOR_WORD_APPROVAL)",
  WAITING_FOR_DOMAIN_APPROVAL: "도메인 승인 대기 (WAITING_FOR_DOMAIN_APPROVAL)",
};

// 대화 중엔 도메인이 정하는 값(허용값/표현형식/저장형식 등)을 따로 묻지 않지만, 등록이
// 끝나는 시점엔 사용자가 그 도메인의 전체 스펙을 알 수 있어야 하므로(2026-09-18) 여기서
// 도메인 코드로 상세를 조회해서 같이 보여준다. registration.submit()의 반환값엔 도메인
// 코드만 있어 이 조회가 필요 - 실패해도(네트워크 등) 등록완료 카드 자체는 계속 보여준다.
async function renderRegistrationCard(mcpState) {
  const reg = mcpState.registration;
  if (!reg) return "";
  if (reg.request_id) {
    const domainCode = reg.domain || mcpState.domain;
    const domain = await fetchDomainDetail(domainCode);
    return summaryCard([
      ["신청 ID", reg.request_id.slice(0, 8) + "…", true],
      ["용어명", reg.term_name || mcpState.term_name],
      ["도메인", domainCode, true],
      ["영문 약어", reg.english_abbr || mcpState.english_abbr, true],
      ["상태", REGISTRATION_STATUS_LABEL[reg.status] || "검토 대기 (PENDING_REVIEW)"],
      ["도메인그룹", domain?.domain_group],
      ["도메인분류", domain?.domain_classification],
      ["데이터유형", domain?.data_type],
      ["데이터길이", [domain?.data_length, domain?.decimal_length].filter((v) => v !== null && v !== undefined).join(",")],
      ["저장형식", domain?.storage_format, true],
      ["표현형식", domain?.display_format, true],
      ["단위", domain?.unit],
      ["허용값", domain?.valid_values],
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
      ["표준 단어명", sug.existing_word_match, true],
      ["영문 약어", sug.english_abbr, true],
      ["영문명", sug.english_name],
      ["정의", sug.definition],
      ["형식단어", sug.is_format_word ? "예" : "아니오"],
      ["도메인분류", sug.domain_classification],
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
    const w = mcpState.resolved_word;
    return summaryCard([
      ["재사용한 표준 단어명", w.name, true],
      ["영문 약어", w.english_abbr, true],
      ["영문명", w.english_name],
      ["정의", w.definition],
      ["형식단어", w.is_format_word ? "예" : "아니오"],
      ["도메인분류", w.domain_classification],
    ], "summary-card-ok");
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

function renderTermLookupTable(mcpState) {
  const matches = (mcpState.term_lookup || {}).matches || [];
  if (!matches.length) return "";
  return `<div class="table-wrap"><table class="data-table">
    <thead><tr><th>용어명</th><th>영문 약어</th><th>도메인</th><th>정의</th><th>동의어</th><th>유사도</th></tr></thead>
    <tbody>${matches.map((m) => `
      <tr>
        <td><strong>${escapeHtml(m.name)}</strong></td>
        <td><span class="mono">${escapeHtml(m.english_abbr || "-")}</span></td>
        <td><span class="mono">${escapeHtml(m.domain || "-")}</span></td>
        <td class="cell-def">${escapeHtml(m.definition || "")}</td>
        <td>${escapeHtml((m.synonyms || []).join(", "))}</td>
        <td>${Math.round((m.similarity || 0) * 100)}%</td>
      </tr>`).join("")}</tbody>
  </table></div>`;
}

// stage별로 어떤 구조화 블록을 붙일지 결정합니다. 서버(build_chatflow.py의
// RENDER 프롬프트)는 이 stage들에서 같은 내용을 문장으로 다시 나열하지
// 않도록 되어 있어, 프론트엔드 표/카드가 유일한 상세 정보 출처입니다.
async function renderStructuredBlock(mcpState) {
  if (!mcpState) return "";
  switch (mcpState.stage) {
    case "awaiting_domain_choice":
      return renderDomainTable(mcpState.domains);
    case "term_lookup_result":
      return renderTermLookupTable(mcpState);
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
      return await renderRegistrationCard(mcpState);
    case "awaiting_word_confirm":
      return renderWordSuggestionCard(mcpState);
    case "awaiting_word_abbreviation":
      return renderWordAbbreviationCard(mcpState);
    case "word_reused":
    case "word_submitted":
    case "word_registration_failed":
    case "word_request_blocked":
      return renderWordResultCard(mcpState);
    case "awaiting_domain_spec_clarify":
    case "awaiting_domain_spec_confirm":
    case "awaiting_domain_pii_choice":
      return renderDomainSuggestionCard(mcpState);
    case "domain_request_blocked":
      return renderDomainRequestBlockedCard(mcpState);
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
  let mcpError = "";
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
          // The action node's own JSON already carries this sibling to .state (see
          // conversation.py's transition() returning {"error": "..."} alongside the
          // unchanged state on a rejected/incomplete turn - e.g. clicking "새 용어를
          // 등록할래요" re-fires propose_term with an empty value, which errors with
          // TERM_REQUIRED and leaves state.stage exactly as it was). Previously unread
          // here, which was the actual bug behind the stale term_lookup_result table
          // reappearing after that click - the reply text already knew to ask for a
          // name (build_chatflow.py's suppress_stage_summary), but nothing told the
          // frontend the leftover table/buttons were now stale too.
          mcpError = payload.data.outputs.error || "";
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

  return { answer, state: mcpState, options, error: mcpError };
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
  // "여기서 마칠게요" always resets state to a bare {"stage":"awaiting_term_direct"}
  // server-side (deterministic, verified directly) - but the reply LLM has shown it
  // will sometimes ignore render_context's close_hint instruction and describe the
  // now-idle stage as if it were asking for a new term name instead (same "prose
  // alone isn't reliable" class of bug already hit with resume_notice). Since this
  // button's outcome never varies, skip the LLM's text for it entirely rather than
  // fight the prompt further, and show the same opening menu as the very first
  // greeting so there's something to click instead of a dead end.
  const isCloseAction = raw === CLOSE_VALUE;

  try {
    const { answer, state: mcpState, options, error: mcpError } = await streamChatMessage(raw, {
      onStep: (nodeId, status) => setStepState(tracker, nodeId, status),
      onAnswerChunk: (partial) => {
        if (isCloseAction) return;
        setBubbleContent(bubble, formatAnswer(partial) || '<p class="thinking">답변 작성 중...</p>');
      },
    });

    const closed = isCloseAction && mcpState?.stage === "awaiting_term_direct";
    // word_suggestion.method=="unavailable" means suggest_word() itself threw (e.g. the
    // model returned an incomplete proposal even after a clarification round) - nothing
    // was actually produced. Verified live: the reply LLM sometimes narrates this as if a
    // real candidate WERE ready anyway, apparently recalling a word mentioned earlier in
    // the conversation instead of reporting the failure - a hallucination, not just a
    // wording slip, so (like `closed` above) this bypasses the LLM's text entirely rather
    // than trying to prompt-engineer around it again.
    const wordSuggestionFailed = mcpState?.stage === "awaiting_word_confirm" && mcpState?.word_suggestion?.method === "unavailable";
    setBubbleContent(bubble, formatAnswer(
      closed ? "네, 알겠습니다! 필요하시면 아래 중 하나를 선택하거나 자유롭게 말씀해주세요." :
      wordSuggestionFailed ? "단어 추천을 만드는 데 실패했습니다. 어떤 개념인지 다시 한 번 설명해 주세요." :
      answer));
    tracker.remove();

    // These three errors mean a terminal-stage "새 용어를/단어를 등록할래요" button
    // re-fired propose_term/propose_word/find_term with an empty value on purpose
    // (see CLASSIFY_TERMINAL_RULE) - business logic intentionally leaves state
    // completely unchanged so the old term_lookup_result/word_reused/etc. table and
    // buttons stay technically valid data, but they're no longer what this turn is
    // about (we're now just waiting for a plain-text name/description). Rendering
    // them again looked like the click did nothing and the user was stuck in a loop -
    // reported live. The reply text already knows to ask for the name (build_chatflow.py's
    // suppress_stage_summary); this is the same suppression for the frontend's cards.
    const needsFreshInput = ["TERM_REQUIRED", "WORD_MEANING_REQUIRED", "TERM_MEANING_REQUIRED"].includes(mcpError);

    const structuredHtml = needsFreshInput ? "" : await renderStructuredBlock(mcpState);
    if (structuredHtml) {
      bubble.querySelector(".bubble").classList.add("has-data");
      bubble.querySelector(".bubble").insertAdjacentHTML("beforeend", structuredHtml);
      scrollChatToBottom();
    }

    if (closed) {
      addOptionButtons(bubble, OPENING_MENU_OPTIONS, (value) => submitChatMessage(value));
    } else if (options && options.length) {
      addOptionButtons(bubble, options, (value) => submitChatMessage(value));
    } else if (!needsFreshInput) {
      const terminalActions = terminalActionsFor(mcpState);
      if (terminalActions) addOptionButtons(bubble, terminalActions, (value) => submitChatMessage(value));
    }

    // Alongside "네, 이 정의로 할게요" (from the block above) - only when there's an
    // actual suggested definition on screen to override, not the ambiguous-question
    // or no-suggestion-yet cases, which already just want free text with nothing to opt out of.
    const defSug = mcpState?.definition_suggestion;
    if (mcpState?.stage === "awaiting_definition" && defSug && !defSug.ambiguous && defSug.definition) {
      addWriteOwnDefinitionButton(bubble);
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
