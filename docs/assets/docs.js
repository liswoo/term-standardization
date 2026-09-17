// 페이지마다 사이드바 마크업이 복붙되어 있으므로(빌드 스텝 없음), 현재 파일명과
// href를 비교해서 활성 링크만 코드로 표시한다 - 페이지별로 is-active 클래스를
// 손으로 넣고 다니면 곧 어긋난다.
(function () {
  // 최상위 링크(예: architecture.html)만 활성 표시한다 - 하위 앵커
  // (architecture.html#system 등)도 같은 파일명을 공유하므로, "#"가 없는
  // 링크로만 한정하지 않으면 한 페이지에서 5~6개 링크가 한꺼번에 켜진다.
  const current = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".docs-nav > a").forEach((a) => {
    if (a.getAttribute("href") === current) a.classList.add("is-active");
  });

  const menuBtn = document.getElementById("docs-menu-btn");
  const sidebar = document.querySelector(".docs-sidebar");
  if (menuBtn && sidebar) {
    menuBtn.addEventListener("click", () => sidebar.classList.toggle("is-open"));
    document.querySelectorAll(".docs-nav a").forEach((a) =>
      a.addEventListener("click", () => sidebar.classList.remove("is-open")));
  }
})();
