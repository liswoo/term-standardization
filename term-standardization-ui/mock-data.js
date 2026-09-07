// 메타시스템 목업 데이터 — 실제 DB 연동 없이 화면 시연용으로만 사용됩니다.

const MOCK_DOMAINS = [
  { id: "d1", name: "보건복지", desc: "국민 건강, 영양, 복지 서비스 관련 용어", count: 34, color: "#2563eb" },
  { id: "d2", name: "행정", desc: "행정구역, 민원, 인허가 관련 용어", count: 28, color: "#7c3aed" },
  { id: "d3", name: "교육", desc: "학교, 교육과정, 학생 정보 관련 용어", count: 19, color: "#059669" },
  { id: "d4", name: "환경", desc: "대기질, 폐기물, 에너지 관련 용어", count: 15, color: "#d97706" },
  { id: "d5", name: "산업경제", desc: "사업자, 통계, 산업분류 관련 용어", count: 22, color: "#db2777" },
  { id: "d6", name: "미분류", desc: "도메인 분류가 아직 필요한 용어", count: 10, color: "#64748b" },
];

const MOCK_TERMS = [
  {
    id: "t1", name: "일일권장열량", enAbbr: "RDA_CAL",
    def: "성인 1인 기준 하루에 섭취를 권장하는 총 열량 기준값",
    domain: "보건복지", synonyms: ["일일권장칼로리", "권장섭취열량"],
    status: "승인", date: "2026-08-02",
  },
  {
    id: "t2", name: "행정구역코드", enAbbr: "ADM_CD",
    def: "행정안전부가 관리하는 시·군·구 단위 행정구역 식별 코드",
    domain: "행정", synonyms: ["법정동코드"],
    status: "승인", date: "2026-07-18",
  },
  {
    id: "t3", name: "사업자등록번호", enAbbr: "BIZ_NO",
    def: "국세청이 부여하는 사업체 고유 식별 번호",
    domain: "산업경제", synonyms: ["사업자번호"],
    status: "승인", date: "2026-07-11",
  },
  {
    id: "t4", name: "대기질예보등급", enAbbr: "AQ_GRADE",
    def: "미세먼지 및 초미세먼지 농도를 기준으로 구분한 대기질 예보 등급",
    domain: "환경", synonyms: ["미세먼지등급"],
    status: "검토중", date: "2026-08-20",
  },
  {
    id: "t5", name: "학생기초학력진단", enAbbr: "STU_BASIC_DX",
    def: "초·중학교 학생의 기초 학력 수준을 진단하는 평가 지표",
    domain: "교육", synonyms: [],
    status: "승인", date: "2026-06-30",
  },
  {
    id: "t6", name: "복지서비스대상자구분", enAbbr: "WF_TARGET_TYPE",
    def: "복지 서비스 수혜 대상자를 소득·연령 기준으로 분류한 구분값",
    domain: "보건복지", synonyms: ["복지대상구분코드"],
    status: "검토중", date: "2026-08-25",
  },
];

const MOCK_ACTIVITY = [
  { text: "‘복지서비스대상자구분’ 검토 요청", who: "김도현", time: "10분 전" },
  { text: "‘대기질예보등급’ 신규 등록", who: "박서연", time: "2시간 전" },
  { text: "‘사업자등록번호’ 동의어 추가 승인", who: "우종민", time: "어제" },
  { text: "‘학생기초학력진단’ 정의 수정", who: "이하늘", time: "2일 전" },
];
