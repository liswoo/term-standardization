// 메타시스템 목업 데이터 — 실제 DB 연동 없이 화면 시연용으로만 사용됩니다.
// 페이지 로드 직후 실제 백엔드 조회(fetchTermsFromBackend)가 끝나기 전까지
// 잠깐 보여주는 자리표시자일 뿐, 조회가 끝나면 바로 실제 데이터로 교체됩니다.
// 도메인은 백엔드(domains 테이블)에 실제로 존재하는 4개 데이터 도메인
// (수N7/명V100/율N5,2/코드C2)의 코드만 표시합니다 — 부연 설명은 붙이지 않습니다.

const MOCK_TERMS = [
  {
    id: "t1", name: "일일권장열량", enAbbr: "RDA_CAL",
    def: "성인 1인 기준 하루에 섭취를 권장하는 총 열량 기준값",
    domain: "수N7", synonyms: ["일일권장칼로리", "권장섭취열량"],
    status: "승인", date: "2026-08-02",
  },
  {
    id: "t2", name: "행정구역코드", enAbbr: "ADM_CD",
    def: "행정안전부가 관리하는 시·군·구 단위 행정구역 식별 코드",
    domain: "코드C2", synonyms: ["법정동코드"],
    status: "승인", date: "2026-07-18",
  },
  {
    id: "t3", name: "사업자등록번호", enAbbr: "BIZ_NO",
    def: "국세청이 부여하는 사업체 고유 식별 번호",
    domain: "명V100", synonyms: ["사업자번호"],
    status: "승인", date: "2026-07-11",
  },
  {
    id: "t4", name: "대기질예보등급", enAbbr: "AQ_GRADE",
    def: "미세먼지 및 초미세먼지 농도를 기준으로 구분한 대기질 예보 등급",
    domain: "코드C2", synonyms: ["미세먼지등급"],
    status: "검토중", date: "2026-08-20",
  },
  {
    id: "t5", name: "학생기초학력진단", enAbbr: "STU_BASIC_DX",
    def: "초·중학교 학생의 기초 학력 수준을 진단하는 평가 지표",
    domain: "명V100", synonyms: [],
    status: "승인", date: "2026-06-30",
  },
  {
    id: "t6", name: "복지서비스대상자구분", enAbbr: "WF_TARGET_TYPE",
    def: "복지 서비스 수혜 대상자를 소득·연령 기준으로 분류한 구분값",
    domain: "코드C2", synonyms: ["복지대상구분코드"],
    status: "검토중", date: "2026-08-25",
  },
];

// 실제 백엔드 조회가 끝나기 전까지의 로딩 자리표시자 (activityFromTerms로 교체됨).
const MOCK_ACTIVITY = [
  { text: "실제 등록 활동을 불러오는 중…", who: "", time: "" },
];
