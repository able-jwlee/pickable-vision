from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app import config

# 각 필드의 description 은 **API 소비자(프론트엔드)** 를 위한 것이다 —
# /openapi.json 에 그대로 실려 폼 라벨·툴팁·타입 생성에 쓰인다.
# 짧고 조작적으로 쓸 것. 실측 곡선과 기각 사유 같은 근거는 아래 주석과
# app/config.py 에 남긴다(그쪽은 이 코드를 고칠 사람을 위한 것이다).


class DetectRequest(BaseModel):
    # 이미지 입력: base64(image) 또는 로컬 경로(image_path) 중 하나.
    # image_path는 로컬 튜닝 편의용 — 서버와 파일시스템을 공유할 때만 동작.
    image: str | None = Field(
        None,
        description=(
            "입력 이미지 base64. `data:image/...;base64,` 접두사를 붙여도 된다. "
            "브라우저 흐름에서 쓰는 **운영 계약**이다. "
            "`image` 와 `image_path` 중 하나는 반드시 있어야 한다."
        ),
    )
    image_path: str | None = Field(
        None,
        description=(
            "서버 로컬 파일 경로. **개발·튜닝 편의용**이며 서버와 파일시스템을 "
            "공유할 때만 동작한다. 운영 배포에서는 쓰지 말 것. "
            "`image` 와 함께 오면 이쪽이 우선한다."
        ),
    )
    # 콜로니가 한천보다 밝은지 어두운지. 오퍼레이터가 눈으로 판단할 수 있다.
    # 실측: 맞는 극성으로 고정하면 **모든 그룹에서 정밀도가 오른다**
    #   lower-res(밝은) 92.7 → 97.9% · dark(어두운) 90.3 → 95.2%
    #   bright(어두운) 93.6 → 95.0% · vague(어두운) 75.9 → 84.5%
    # 재현율 손실은 거의 없다 — 틀린 극성 분기는 기여 없이 오검출만 추가했다.
    # 그렇게 확보한 정밀도 여유를 감도로 바꾸면 재현율을 올릴 수 있다.
    #   "auto"   → **접시별로 자동 판정** (기본). 실측 39장에서 판정 정확도
    #              100%이고, 양극성 병합보다 모든 운영점에서 재현율이 3%p 이상
    #              높다 (config.BLOB_AUTO_POLARITY 주석의 곡선 참조).
    #   "both"   → 양극성 모두 검출 후 병합 (이전 "auto" 동작). 자동 판정이
    #              틀리는 접시가 발견되면 이 값으로 되돌릴 수 있다.
    #   "bright"/"dark" → 그 극성만 본다
    polarity: Literal["auto", "both", "bright", "dark"] = Field(
        "auto",
        description=(
            "콜로니가 한천보다 밝은지 어두운지. "
            "`auto` = 접시별 자동 판정(기본, 실측 39장 판정 정확도 100%). "
            "`bright`/`dark` = 그 극성만 검출. "
            "`both` = 양극성 병합 — 자동 판정이 틀릴 때의 되돌림 경로. "
            "**기본값 유지를 권장한다.**"
        ),
    )
    # blob 경로의 플레이트 기하구조. 자동 판정은 판별력이 없어(blob_detector의
    # plate_roi docstring 참조) 호출자가 명시한다.
    #   "petri" → 원형 접시. "well8" → 4×2 몰딩 8웰 플레이트.
    plate_type: Literal["petri", "well8"] = Field(
        "petri",
        description=(
            "플레이트 기하구조. `petri` = 원형 접시(HoughCircles 로 ROI 검출), "
            "`well8` = 4×2 몰딩 8웰 플레이트(격자 ROI). "
            "자동 판정은 판별력이 없어 호출자가 명시해야 한다."
        ),
    )
    # ------------------------------------------------------------------
    # blob 경로 파라미터. 기본값은 sample/ 라벨 39장(정답 1,886개) 실측
    # 최적값이고, 각 필드의 실측 곡선은 app/config.py 주석에 기록돼 있다.
    # 이미지마다 조절할 필요가 있는 것만 노출한다 — 밝기·콜로니 극성(밝은지
    # 어두운지)·접시 위치와 크기는 알고리즘이 자동 처리하므로 knob이 없다.
    # ------------------------------------------------------------------
    # 감도. 면적 가중 t-통계량 하한 — 낮추면 흐린 콜로니까지 잡고(재현율↑)
    # 오검출이 늘어난다. None이면 sensitivity(0~100) 매핑, 그것도 없으면 기본값.
    # 실측(2026-08-07, 현재 설정): 30 → 정밀도 89.0%/재현율 70.9%,
    #   25 → 86.7%/73.3% (F1 최고 79.4), 20 → 82.2%/75.7% (기본),
    #   15 → 73.5%/77.3%
    min_t: float | None = Field(
        None,
        ge=1.0,
        le=200.0,
        description=(
            "감도 원본값 — 면적가중 Welch t-통계량 하한. 낮출수록 흐린 콜로니까지 "
            "잡아 재현율이 오르고 정밀도가 내린다. "
            "실측: 30 → 89.0%/70.9%, 25 → 86.7%/73.3%, **20 → 82.2%/75.7%(기본)**, "
            "15 → 73.5%/77.3% (정밀도/재현율). "
            "생략하면 `sensitivity` 매핑, 그것도 없으면 서버 기본값(20)을 쓴다. "
            "**오퍼레이터 UI 는 이 값 대신 `sensitivity` 를 보낼 것.**"
        ),
    )
    # 콜로니 크기 창 — 지름 ÷ 접시 지름. 0 = 제한 없음(기본값).
    # 비율이라 해상도·카메라와 무관하다. 실측 분포: 1.2%~45%, 중앙값 7%.
    min_diam_frac: float = Field(
        config.BLOB_MIN_DIAM_FRAC,
        ge=0.0,
        le=1.0,
        description=(
            "콜로니 크기 하한 — 콜로니 지름 ÷ **기준 길이**. 0 = 제한 없음(기본). "
            "비율이라 해상도·카메라와 무관하다. 실측 분포 1.2~45%, 중앙값 7%. "
            "기준 길이는 `plate_type=\"petri\"` 에서 접시 지름이지만, `well8` 이거나 "
            "접시 검출이 실패하면 **이미지 짧은 변**으로 폴백한다 — 서버가 실제로 쓴 "
            "값이 응답 `applied_params.plate_size_ref`(원본 px) 에 담기므로 "
            "\"5% = 몇 px\" 은 그것으로 계산할 것."
        ),
    )
    max_diam_frac: float = Field(
        config.BLOB_MAX_DIAM_FRAC,
        ge=0.0,
        le=1.0,
        description=(
            "콜로니 크기 상한 — 콜로니 지름 ÷ **기준 길이**(`min_diam_frac` 와 같은 "
            "분모, `applied_params.plate_size_ref`). 0 = 제한 없음(기본). "
            "**켤 때 주의** — 실측 콜로니 지름이 기준 길이의 1.2~45% 로 매우 넓어 "
            "어떤 상한도 진짜 큰 콜로니를 버린다. 상한이 막으려는 대상(뭉친 덩어리·"
            "접시 테두리)은 이미 `watershed_split` 과 접시 반지름 수축이 담당하므로 "
            "오퍼레이터 UI 에는 하한만 노출하는 것을 권한다."
        ),
    )
    # 색이 뚜렷하면 감도 요구치를 이 배율까지 깎아준다. 1.0 = 끔(기본값, 유지 권장).
    # 재측정(2026-08-12, candidate_source="union" 기준): 켜면 네 그룹 전부
    # 나빠진다 — 2.0배에서 정밀도 82.20%→59.82%, 재현율 75.7%→79.2%,
    # F1 78.80→68.14. 오퍼레이터 UI 에 노출하지 않는다.
    colour_credit: float = Field(
        config.BLOB_COLOUR_CREDIT_MAX,
        ge=1.0,
        le=8.0,
        description=(
            "색이 뚜렷한 후보의 감도 요구치를 이 배율까지 깎아준다. 1.0 = 끔(기본, 유지 권장). "
            "**현재 설정(candidate_source=\"union\")에서 켜면 전 그룹이 나빠진다** — "
            "실측 2.0배에서 정밀도 82.20%→59.82%, 재현율 75.7%→79.2%, F1 78.80→68.14 "
            "(그룹별 F1: lower 83.2→67.3, bright 80.7→74.6, dark 83.7→70.0, vague 61.6→52.7). "
            "정밀도를 22%p 깎고 재현율은 3.5%p 만 얻으므로 오퍼레이터 UI 에 노출하지 말 것."
        ),
    )
    # 색 게이트 본체. 잉크·데브리는 -0.1~+1.7, 콜로니는 7~57 로 판별력이 크다.
    # 실측(39장): 0 → 77.5%/76.2%, 1.5 → 82.2%/75.7%(기본), 3.0 → 84.0%/74.7%,
    #   6.0 → 88.2%/69.2%, 12.0 → 93.0%/60.8% (정밀도/재현율)
    # 3.0 이 전역 F1 최고(79.03 대 78.80)지만 기본값 변경은 별건으로 다룬다.
    # 기본값을 config 에서 직접 실어 openapi 스펙에 `default: 1.5` 가 뜨게 한다.
    # None 으로 두면 프론트가 생성한 타입에 기본값이 없어 UI 초기값을 손으로
    # 복제하게 되고, 이 프로젝트는 그 복제 때문에 표시가 서버와 어긋난 적이 있다.
    # 여전히 nullable 이라 명시적 null 은 서버 기본값으로 해소된다(api.py).
    min_rel_sat: float | None = Field(
        config.BLOB_MIN_REL_SAT,
        ge=0.0,
        le=60.0,
        description=(
            "색 차이 요구 — |내부채도 − 주변채도| 하한. 0 = 끔. "
            "인쇄 글씨·데브리는 이 값이 0 근처(−0.1~1.7)이고 콜로니는 7~57 이라 "
            "**오검출을 걷어내는 가장 강한 레버**다. "
            "실측: 0 → 77.5%/76.2%, **1.5 → 82.2%/75.7%(기본)**, "
            "3.0 → 84.0%/74.7%, 6.0 → 88.2%/69.2%, 12.0 → 93.0%/60.8% "
            "(정밀도/재현율). 생략하면 서버 기본값. "
            "무채색 이미지에서는 서버가 색 축을 끄므로 이 값이 무시된다 — "
            "응답 `applied_params.has_chroma` 로 확인할 것. "
            "0 이면 `colour_credit` 도 함께 무력화된다 — 내부적으로 이 값을 "
            "분모로 나누기 때문이다."
        ),
    )
    # 처리 해상도(최대변 px). 콜로니당 픽셀 수가 t-통계량을 좌우한다.
    # BLOB_R_MIN/R_MAX 와 **반드시 함께 움직여야 한다** (config 주석 참조).
    work_size: int = Field(
        config.BLOB_WORK_SIZE,
        ge=384,
        le=2048,
        description=(
            "처리 해상도(최대변 px). 콜로니당 픽셀 수가 t-통계량을 좌우한다. "
            "1280 이 실측 최적이고 2048 은 전 그룹에서 나쁘다. "
            "**바꾸면 크기 창 캘리브레이션이 무효가 된다** — 단독 변경 금지."
        ),
    )
    # 후보 생성 방식.
    #   "union"(기본) = LoG ∪ 이진화. 실측상 전 구간에서 LoG 단독보다
    #                   +2.9~3.5%p 위다 — 두 방식이 서로 다른 것을 보기 때문.
    #                   후보 커버리지 LoG 93.4% / 이진화 89.7% / 합집합 95.4%.
    #   "log"       = LoG 단독 (구동작).
    #   "threshold" = 이진화 단독. 정밀도 93% 이상 구간에서는 이쪽이 합집합보다
    #                 낫다(94%에서 67.3% 대 62.9%) — 계수(CFU) 용도에 적합.
    candidate_source: Literal["union", "log", "threshold"] = Field(
        config.BLOB_CANDIDATE_SOURCE,
        description=(
            "후보 생성 방식. `union` = LoG ∪ 다중레벨 이진화(기본, 재현율 우선) — "
            "전 구간에서 LoG 단독보다 +2.9~3.5%p 위다. "
            "`threshold` = 이진화 단독 — **정밀도 93% 이상 구간에서는 이쪽이 낫다** "
            "(계수/CFU 용도). `log` = LoG 단독(구동작)."
        ),
    )
    # 이진화 후보의 임계값 레벨 수. 12/24/36 에서 재현율 67.9/70.8/71.3% 로
    # 24 에서 포화한다. 늘려도 커버리지 천장(~90%)은 안 오른다.
    threshold_levels: int = Field(
        config.BLOB_THRESHOLD_LEVELS,
        ge=2,
        le=64,
        description=(
            "이진화 후보의 임계값 레벨 수 (`candidate_source` 가 union/threshold 일 때). "
            "12/24/36 → 재현율 67.9/70.8/71.3% 로 **24 에서 포화한다** — "
            "늘려도 커버리지 천장(약 90%)은 오르지 않고 비용만 는다."
        ),
    )
    # 둘레 기반 원형도 4πA/P². **기본 0 = 끔.** 경계 거칠기에 극도로 민감해
    # 합집합 후보(이진화 성분은 둘레가 거칠다)를 부당하게 버렸다. 모양 판정은
    # min_roundness(면적 기반)가 담당한다.
    min_circularity: float = Field(
        config.BLOB_MIN_CIRCULARITY,
        ge=0.0,
        le=1.0,
        description=(
            "둘레 기반 원형도 4πA/P² 하한. **기본 0 = 끔.** "
            "경계 거칠기에 극도로 민감해 합집합 후보의 이진화 성분(둘레가 거칠다)을 "
            "부당하게 버렸다 — 끄자 재현율 74.4 → 75.7%. "
            "모양 판정은 면적 기반 `min_roundness` 가 담당한다."
        ),
    )
    # 채움율 A/(bounding box 면적). 0.60 으로 올리면 정밀도 92~96% 구간에서
    # +1.4~2.1%p — 계수 용도처럼 정밀도가 중요할 때 쓴다.
    min_fill: float = Field(
        config.BLOB_MIN_FILL,
        ge=0.0,
        le=1.0,
        description=(
            "채움율 하한 — 윤곽 면적 ÷ bounding box 면적. "
            "0.60 으로 올리면 정밀도 92~96% 구간에서 +1.4~2.1%p 이므로 "
            "계수(CFU) 용도에 쓸 만하다. 기본 운영점에서는 이득이 없다."
        ),
    )
    # 분리 — 붙은 콜로니를 거리변환 watershed 로 나눈다.
    #   watershed_split  끄면 뭉친 군집이 하나로 검출된다. **끄면 나빠지기만 한다**
    #                    (실측: 한 접시에서 맞힘 7개 감소). 이상하게 잘릴 때만 끄는
    #                    비상구이지 조정 knob 이 아니다.
    #   split_area_ratio 자연 윤곽 면적이 기대 면적의 이 배를 넘으면 병합으로 본다.
    #                    낮출수록 적극적으로 나눈다.
    watershed_split: bool = Field(
        config.BLOB_WATERSHED_SPLIT,
        description=(
            "붙은 콜로니를 거리변환 watershed 로 분리한다. "
            "**끄면 나빠지기만 한다** — 이상하게 잘리는 접시가 있을 때만 쓰는 "
            "비상구이지 조정 knob 이 아니다."
        ),
    )
    split_area_ratio: float = Field(
        config.BLOB_SPLIT_AREA_RATIO,
        ge=0.5,
        le=5.0,
        description=(
            "윤곽 면적이 후보 기대 면적(π r²)의 이 배를 넘으면 병합으로 보고 분리한다. "
            "낮출수록 적극적으로 나눈다. "
            "**반지름 보정과 함께 움직인다** — 반지름을 바꾸면 이 값도 재보정해야 한다."
        ),
    )
    # 중첩 검출 제외. **기본 끔** — 실측상 어느 문턱에서도 F1 이 내려간다
    # (0.8 에서 ΔF1 -0.23). 억제 대상의 절반 이상이 정답이기 때문이다.
    # 특정 접시에서 눈에 거슬릴 때 켜는 비상구이지 조정 knob 이 아니다.
    exclude_nested: bool = Field(
        False,
        description=(
            "`parent_id` 가 붙은 검출을 `colonies` 에서 빼고 `count` 도 줄인다. "
            "**기본 끔** — 실측 39장에서 F1 이 0.23 내려간다(제외 대상 30개 중 "
            "16개가 정답). 같은 콜로니를 두 번 집는 것을 막고 싶을 때만 켠다. "
            "켜면 남는 검출의 `parent_id` 는 모두 `null` 이고 `id` 는 1부터 "
            "다시 매겨진다. `pick_top_n` 은 제외 **전** 전체 집합에서 상위 N 을 "
            "고르므로, 함께 쓰면 `pickable` 이 N 보다 적을 수 있다."
        ),
    )
    # 모양 게이트. 재현율을 더 짜내야 할 때 접시별로 푸는 용도이고, 기본값이
    # 이미 실측 최적이라 보통은 건드릴 필요가 없다.
    #   min_solidity  면적 ÷ convex hull 면적. 오목한 얼룩·긁힘 배제.
    #                 0.75 아래로는 결과가 변하지 않는다(포화).
    #   min_roundness 면적 ÷ 최소외접원 면적. 주된 모양 판정.
    #                 **완화를 권하지 않는다** — 같은 정밀도(82.8%)에서 감도를
    #                 내리는 쪽이 더 많이 맞힌다(74.7% 대 72.5%).
    # 0 = 해당 게이트 끔.
    min_solidity: float = Field(
        config.BLOB_MIN_SOLIDITY,
        ge=0.0,
        le=1.0,
        description=(
            "면적 ÷ convex hull 면적 하한. 오목한 얼룩·긁힘을 배제한다. 0 = 끔. "
            "0.75 아래로는 결과가 변하지 않는다(포화)."
        ),
    )
    min_roundness: float = Field(
        config.BLOB_MIN_ROUNDNESS,
        ge=0.0,
        le=1.0,
        description=(
            "면적 ÷ 최소외접원 면적 하한 — **주된 모양 판정**. 0 = 끔. "
            "**완화를 권하지 않는다.** 같은 정밀도(82.8%)에서 이 값을 0.45 로 푸는 "
            "것보다 감도를 내리는 쪽이 더 많이 맞힌다 (74.7% 대 72.5%)."
        ),
    )
    # 오퍼레이터가 화면에서 찍은 콜로니 색 (R, G, B). color_boost 와 함께 켠다.
    # 색을 gray 의 대체가 아니라 max 로 더하므로, 잘못 찍어도 최악이 기본 동작과
    # 같다 — polarity 를 UI 에 노출하지 않는 이유(틀리면 붕괴)가 여기엔 없다.
    target_color: list[Annotated[int, Field(ge=0, le=255)]] | None = Field(
        None,
        min_length=3,
        max_length=3,
        description=(
            "오퍼레이터가 화면에서 찍은 콜로니 색 `[R, G, B]` (각 0~255). "
            "**이 색에 가까운 콜로니를 더 잘 찾는다** — 검출 후 거르는 게 아니라 "
            "검출 자체를 돕는다. `color_boost` 가 0 이면 무시된다.\n\n"
            "밝기를 뺀 색상 평면(Lab a\\*b\\*)에서 거리를 재므로 그늘져서 어두운 "
            "같은 색 콜로니도 인정한다.\n\n"
            "**색은 화면에서 찍게 할 것.** 숫자로 입력받으면 촬영마다 조명·"
            "화이트밸런스가 달라 같은 콜로니가 다른 값으로 찍힌다. 같은 이미지 안에서 "
            "고르면 그 문제가 없다."
        ),
    )
    # 색 선별. **colonies 에서 빼지 않고 pickable 만 내린다** — 화면이 "왜 빠졌는지"
    # 를 보여줄 수 있어야 오퍼레이터가 색을 잘못 찍은 것을 알아챈다. exclude_nested
    # 를 기본 끔으로 둔 이유와 같다(제외 대상의 절반이 정답이었다).
    max_color_distance: float | None = Field(
        config.BLOB_MAX_COLOR_DISTANCE,
        ge=0.0,
        le=200.0,
        description=(
            "색 선별 — `target_color` 까지의 Lab a\\*b\\* 거리가 이 값을 넘는 검출은 "
            "`pickable=false` 가 된다. **기본 20.**\n\n"
            "**`target_color` 를 준 요청에만 적용된다** — 색을 안 주면 이 값은 "
            "아무 일도 하지 않는다. 즉 색을 찍지 않는 한 기존 동작 그대로다.\n\n"
            "**색을 찍으면 거르기까지 기본 동작이다.** 3초 기다려 재검출했는데 "
            "결과가 그대로면 오퍼레이터는 기능이 고장난 줄 안다 — 무언가 "
            "달라져야 답이 된다. 찾기만 하고 거르지 않으려면 **200** 을 준다.\n\n"
            "**`colonies` 에서 빠지지는 않는다.** 걸러진 것도 좌표와 "
            "`color_distance` 를 그대로 받으므로 화면에서 회색으로 보여줄 수 있다 — "
            "그래야 색을 잘못 찍었을 때 오퍼레이터가 알아챈다.\n\n"
            "**`pick_top_n` 보다 먼저 적용된다.** 색으로 거른 뒤 상위 N 개를 "
            "고르므로 96핀을 요청하면 색 조건을 만족하는 96개가 나온다.\n\n"
            "눈금 감각 — 라벨 1,875개 실측: 대표 콜로니를 찍었을 때 **같은 접시 "
            "나머지까지 중앙 2.0 · p99 16.5** 이고, 상한 20 이면 99.7% 가 통과한다. "
            "다른 색 무리는 30~65 이고 갈색→자홍이 80.6 이다. "
            "값을 감으로 정하지 말고 응답의 `color_distance` 분포를 히스토그램으로 "
            "그려 자르게 할 것 — 크기 축과 같은 방식이다.\n\n"
            "찾기를 돕는 `color_boost` 와 **반대 방향이고 함께 쓸 수 있다** "
            "(색으로 더 찾고 + 색으로 거르기)."
        ),
    )
    color_boost: float = Field(
        config.BLOB_COLOR_BOOST,
        ge=0.0,
        le=1.0,
        description=(
            "찍은 색 축의 가중치. **0 = 끔(기본).** 권장값 0.5~0.6.\n\n"
            "**이것은 필터가 아니다.** 그 색 콜로니를 *더 찾아줄* 뿐, 다른 색을 "
            "빼지 않는다 — 자홍을 찍어도 갈색 콜로니는 그대로 나온다. "
            "거르려면 `max_color_distance` 를 쓸 것.\n\n"
            "켜면 `t = max(t_밝기, boost × t_색)` 이라 **기본 동작보다 나빠질 수 "
            "없다** — 색을 잘못 찍어도 최악이 지금과 같다.\n\n"
            "실측(목표색을 제대로 찍은 경우, 정밀도/재현율/F1):\n"
            "가장 못 잡는 `vague` 10장 — 0: 70.2%/54.9%/61.6 → "
            "**0.6: 70.6%/59.0%/64.3**\n"
            "대조군 `bright` 4장 — 0: 83.3%/75.6%/79.3 → 0.6: 82.7%/77.9%/80.2\n\n"
            "**교환이 아니다.** vague 에서 재현율 +4.1%p 를 얻는데 정밀도가 "
            "+0.4%p 로 같이 오른다. 흐린 접시에서 먼저 켜볼 것."
        ),
    )

    # true면 1차 검출로 콜로니 크기를 재고 해상도를 자동 조정해 재검출한다
    # (검출 비용 약 2배). 기본 끔 — 실측에서 전체 F1이 오히려 떨어졌다
    # (config.BLOB_ADAPTIVE_SCALE 주석 참조). 해상도는 work_size로 지정할 것.
    adaptive_scale: bool = Field(
        config.BLOB_ADAPTIVE_SCALE,
        description=(
            "1차 검출로 콜로니 크기를 재고 해상도를 자동 조정해 재검출한다. "
            "**검출 비용이 약 2배가 되고 실측 F1 은 오히려 떨어진다.** "
            "해상도는 `work_size` 로 직접 지정할 것."
        ),
    )

    # ------------------------------------------------------------------
    # 피킹 후보 판정 — 검출된 콜로니 중 로봇이 실제로 집을 것을 고른다.
    # 반지름 단위는 원본 이미지 픽셀이므로 해상도가 다른 카메라로 바꾸면
    # 함께 조정해야 한다(기본값은 8웰 플레이트 기준으로 튜닝된 값이다).
    # ------------------------------------------------------------------
    pick_radius_min: float | None = Field(
        None,
        ge=0.0,
        description=(
            "피킹 대상으로 인정할 최소 반지름(**원본 이미지 픽셀**). "
            "생략하면 서버 기본값. 해상도가 다른 카메라로 바꾸면 재조정해야 한다."
        ),
    )
    pick_radius_max: float | None = Field(
        None,
        ge=0.0,
        description=(
            "피킹 대상으로 인정할 최대 반지름(**원본 이미지 픽셀**). "
            "생략하면 서버 기본값. 0 = 제한 없음."
        ),
    )
    # 웰/접시 경계에서 안쪽만 피킹 대상으로 인정할지. False = 경계 제한 없음.
    mask_walls: bool = Field(
        config.DEFAULT_MASK_WALLS,
        description=(
            "접시·웰 경계에서 안쪽만 피킹 대상으로 인정한다(테두리 반점에 핀을 "
            "찍지 않게). False = 경계 제한 없음. "
            "**검출 자체가 아니라 `pickable` 판정에만 영향한다.**"
        ),
    )
    # 주어지면 피킹 후보(pickable) 중 점수 상위 N개만 후보로 남김 (예: 96핀 → 96)
    # ge=1 이 없으면 0/음수가 조용히 통과한다. scoring 은 `ranked[:top_n]` 으로
    # 자르므로 -3 은 "상위 3개"가 아니라 **하위 3개를 뺀 전부**가 되고, 0 은
    # pickable 을 전멸시킨다. 둘 다 오퍼레이터가 알아챌 수 없는 오동작이다.
    pick_top_n: int | None = Field(
        None,
        ge=1,
        description=(
            "피킹 후보 중 `score` 상위 N개만 `pickable=true` 로 남긴다 "
            "(예: 96핀 헤드 → 96). 생략하면 제한 없음. 1 이상. "
            "`colonies` 배열 자체는 줄지 않는다(`exclude_nested` 는 줄인다). "
            "랭킹 기준인 `score` 는 **고립도와 원형도**로 결정된다 — "
            "`Colony.score` 설명 참조."
        ),
    )
    # true면 콜로니를 표시한 이미지를 vision/output/ 에 저장 (로컬 확인용)
    save_annotated: bool = Field(
        False,
        description=(
            "검출 표시 이미지를 서버의 `vision/output/` 에 저장하고 경로를 "
            "`annotated_path` 로 돌려준다. **개발·디버깅용** — 서버 디스크에 "
            "파일을 쓰므로 운영 UI 에서 쓰지 말 것."
        ),
    )
    # true면 **응답에** 표시 이미지를 base64로 함께 담는다 (좌표와 한 번에).
    # /detect/preview 는 이미지만 주고 좌표를 주지 않으므로, 둘을 같이 받으려면
    # 이 플래그를 쓴다.
    return_image: bool = Field(
        False,
        description=(
            "표시 이미지를 `annotated_image`(base64)로 응답에 함께 담는다. "
            "**웹 UI 에서는 쓰지 말 것** — 4000px 이미지 기준 260KB 로 "
            "좌표만 받을 때(3.9KB)보다 67배 크고, 확대하면 마커가 뭉개진다. "
            "좌표를 렌더링할 수 없는 클라이언트용이다."
        ),
    )
    # 응답 이미지 형식. 4000px급 원본을 PNG로 담으면 응답이 수십 MB가 된다.
    image_format: Literal["jpeg", "png"] = Field(
        "jpeg",
        description=(
            "`return_image` 응답 이미지 형식. "
            "4000px 급 원본을 PNG 로 담으면 응답이 수십 MB 가 된다."
        ),
    )
    image_quality: int = Field(
        85,
        ge=30,
        le=100,
        description="`return_image` JPEG 품질 (`image_format=\"jpeg\"` 일 때만).",
    )
    # 표시 마커 모양. "square"(기본) = 정사각 테두리, "circle" = 원.
    # 콜로니가 원형이라 원을 그리면 윤곽선과 겹쳐 구분이 어렵다 — 직선 테두리가
    # 한천 텍스처 위에서 훨씬 잘 보인다.
    marker: Literal["square", "circle"] = Field(
        "square",
        description=(
            "서버가 그리는 모든 표시 이미지(`return_image` · `/detect/preview` · "
            "`save_annotated`)의 마커 모양. 콜로니가 원형이라 원을 그리면 윤곽선과 "
            "겹쳐 구분이 어렵다 — 직선 테두리가 한천 텍스처 위에서 훨씬 잘 보인다."
        ),
    )
    # 응답 이미지 최대 폭(px). 0이면 원본 크기. 좌표는 항상 원본 픽셀 기준이며,
    # 축소된 경우 응답의 annotated_image_scale 을 곱해야 이미지 위 좌표가 된다.
    image_max_width: int = Field(
        1600,
        ge=0,
        le=8000,
        description=(
            "`return_image` 응답 이미지 최대 폭(px). 0 = 원본 크기. "
            "좌표(`colonies`)는 축소와 무관하게 **항상 원본 픽셀 기준**이며, "
            "축소된 이미지 위에 겹치려면 `annotated_image_scale` 을 곱해야 한다."
        ),
    )
    # 표시(저장/프리뷰 이미지) 모드:
    #   "all"  → 검출 전체를 붉은 원으로 (카운트/분석용, 기본)
    #   "pick" → 피킹 대상(pickable)만 초록 원으로 (로봇이 실제 집을 안전 후보만)
    # 어느 쪽이든 응답 JSON의 colonies/pickable/score는 동일하게 전부 반환된다.
    annotate: Literal["all", "pick"] = Field(
        "all",
        description=(
            "표시 이미지 모드. `all` = 검출 전체를 빨강으로, "
            "`pick` = 피킹 대상(`pickable`)만 초록으로. "
            "**응답 JSON 의 `colonies` 는 어느 쪽이든 전부 동일하게 반환된다** — "
            "그리기에만 영향한다."
        ),
    )

    # 오퍼레이터용 0~100 추상 스케일. 있으면 대응하는 raw 필드보다 우선.
    #   sensitivity → min_t (감도)
    #   edge_margin → 피킹 안전 여백(px)
    sensitivity: int | None = Field(
        None,
        ge=0,
        le=100,
        description=(
            "감도 (오퍼레이터용 0~100). 높을수록 흐린 콜로니까지 잡는다. "
            "`min_t` 로 매핑되며 `min_t` 를 직접 주면 그쪽이 우선한다. "
            "실측: 43 → 89.0%/70.9%, 46 → 86.7%/73.3%, **50 → 82.2%/75.7%(기본)**, "
            "81 → 73.5%/77.3% (정밀도/재현율). "
            "**매핑식을 클라이언트에 복제하지 말 것** — 실제 적용값이 "
            "응답 `applied_params.min_t` 로 되돌아온다."
        ),
    )
    edge_margin: int | None = Field(
        None,
        ge=0,
        le=100,
        description=(
            "피킹 안전 여백 (오퍼레이터용 0~100). 접시·웰 경계에서 이만큼 안쪽만 "
            "피킹 대상으로 인정한다. 실제 적용된 px 값은 "
            "응답 `applied_params.pick_edge_margin` 에 담긴다."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "image_path": "sample/higher-resolution/dark/14581.jpg",
                    "sensitivity": 50,
                    "polarity": "auto",
                    "plate_type": "petri",
                }
            ]
        }
    }

    @model_validator(mode="after")
    def _colour_axis_needs_a_target(self) -> "DetectRequest":
        """색 노브를 켰는데 목표색이 없으면 **조용히 무동작**이 된다.

        이번에 UI 가 자홍을 지정하고 갈색 콜로니가 그대로 나오는 것을 보고 기능이
        고장난 줄 알았던 원인이 정확히 이것이다. 아무 일도 일어나지 않는 것과
        고장난 것을 화면에서 구별할 수 없으므로, 조용히 넘기지 않고 422 로 끊는다.
        """
        if self.target_color is None:
            if self.color_boost > 0:
                raise ValueError(
                    "color_boost 를 쓰려면 target_color 가 있어야 합니다 "
                    "(색을 안 주면 아무 일도 일어나지 않습니다)"
                )
        return self

    @model_validator(mode="after")
    def _require_one_source(self) -> "DetectRequest":
        if not self.image and not self.image_path:
            raise ValueError(
                "either 'image' (base64) or 'image_path' must be provided"
            )
        return self


class Colony(BaseModel):
    id: int = Field(
        description="1부터 시작하는 검출 순번. **재검출하면 달라진다** — 안정적인 식별자가 아니다."
    )
    x: float = Field(description="중심 x 좌표 (**원본 이미지 픽셀**).")
    y: float = Field(description="중심 y 좌표 (**원본 이미지 픽셀**).")
    radius: float = Field(description="반지름 (**원본 이미지 픽셀**).")
    circularity: float = Field(
        1.0,
        description="원형도 0~1. 1에 가까울수록 원. 피킹 품질 참고 지표이며 검출 조건은 아니다.",
    )
    score: float = Field(
        0.0,
        description=(
            "피킹 적합도 0~1. **랭킹용이지 검출 신뢰도가 아니다** — "
            "`pick_top_n` 이 이 값으로 정렬한다.\n\n"
            "`(고립도 x 0.7 + 크기적합도 x 0.3) x (0.5 + 0.5 x circularity)`\n"
            f"- 고립도 = `min(이웃거리 / ({config.PICK_ISOLATION_R_MULT:g} x "
            "자기반지름), 1.0)` — 반지름 배수라 해상도와 무관하다\n"
            "- 크기적합도 = `pick_radius_min`/`max` 대역 안이면 1.0. "
            "**기본값에서는 대역이 꺼져 있어 항상 1.0**(상수)\n"
            "- 원형도 보정이 곱해진다\n\n"
            "따라서 기본값에서 순위를 정하는 것은 **고립도와 원형도**다. "
            "크기로 정렬하려면 `pick_radius_min`/`max` 를 켜야 한다."
        ),
    )
    pickable: bool = Field(
        False,
        description=(
            "로봇이 안전하게 집을 수 있는 후보인지. 이웃과의 거리·크기 대역·"
            "경계 안쪽 여부를 모두 통과해야 true.\n\n"
            "**기본값에서 실제로 거르는 것은 경계 하나다.** 이웃 거리 하한과 "
            "크기 대역은 서버 기본값이 0(=끔)이라 무동작이므로, "
            "`mask_walls=true`(기본)의 접시·웰 경계 마스크만 남는다. "
            "거리·크기로도 거르려면 `pick_radius_min`/`max` 를 명시할 것. "
            "`mask_walls=false` 로 두면 **검출 전부가 pickable** 이 된다."
        ),
    )
    color: list[int] | None = Field(
        None,
        description=(
            "콜로니 내부의 중앙 색 `[R, G, B]` (원본 해상도, 반지름 0.6배 안쪽). "
            "`target_color` 없이도 항상 온다 — 프론트가 이 값으로 스와치를 그리거나 "
            "직접 색 필터를 만들 수 있다."
        ),
    )
    color_distance: float | None = Field(
        None,
        description=(
            "`target_color` 까지의 Lab a\\*b\\* 거리. `target_color` 를 안 보내면 "
            "`null`.\n\n"
            "위 `color` 를 그대로 변환해서 잰 값이라 **프론트가 같은 숫자를 재현할 수 "
            "있다** — \"왜 이게 빠졌는지\" 를 화면에서 설명하려면 그 재현 가능성이 "
            "필요하다.\n\n"
            "`max_color_distance` 를 켰다면 이 값이 그것을 넘는 검출이 "
            "`pickable=false` 인 것들이다."
        ),
    )
    parent_id: int | None = Field(
        None,
        description=(
            "이 검출을 감싸는 더 큰 검출의 `id`. 없으면 `null`. "
            "면적의 80% 이상이 그 검출 안에 들어갈 때 붙는다. "
            "**콜로니 내부 구조에 반응한 중복일 수도, 큰 콜로니 옆의 진짜 작은 "
            "콜로니일 수도 있다** — 실측에서 반반이라 서버는 지우지 않는다. "
            "지우려면 `exclude_nested` 를 쓴다."
        ),
    )


class DetectResponse(BaseModel):
    # width/height 는 **원본 이미지** 크기이고, colonies 의 x/y/radius 도
    # 원본 픽셀 기준이다 (처리 해상도와 무관).
    width: int = Field(description="**원본 이미지** 폭(px). 처리 해상도와 무관하다.")
    height: int = Field(description="**원본 이미지** 높이(px). 처리 해상도와 무관하다.")
    count: int = Field(description="검출된 콜로니 수 (`colonies` 길이와 같다).")
    colonies: list[Colony] = Field(
        description=(
            "검출된 콜로니 전체. 좌표는 항상 원본 픽셀 기준이므로 "
            "SVG `viewBox=\"0 0 {width} {height}\"` 에 그대로 얹으면 된다."
        )
    )
    # save_annotated=true일 때 저장된 이미지 경로, 아니면 null
    annotated_path: str | None = Field(
        None, description="`save_annotated=true` 일 때 서버에 저장된 이미지 경로."
    )
    # return_image=true일 때 콜로니를 표시한 이미지의 base64, 아니면 null.
    annotated_image: str | None = Field(
        None, description="`return_image=true` 일 때 표시 이미지 base64."
    )
    # annotated_image 가 원본 대비 몇 배로 축소됐는지.
    annotated_image_scale: float = Field(
        1.0,
        description=(
            "`annotated_image` 가 원본 대비 몇 배인지. 좌표를 그 이미지 위에 겹치려면 "
            "`x`/`y`/`radius` 에 이 값을 곱한다. 축소하지 않았으면 1.0."
        ),
    )
    # 검출에 실제 적용된 raw 파라미터 dict (튜닝 재현·이슈 리포트용)
    applied_params: dict = Field(
        default={},
        description=(
            "이번 검출에 **서버가 실제로 적용한** raw 파라미터. "
            "`sensitivity` → `min_t` 처럼 매핑된 결과가 들어 있다. "
            "**UI 는 클라이언트에서 재계산하지 말고 이 값을 표시할 것.**"
        ),
    )


class PreviewResponse(BaseModel):
    count: int = Field(description="검출된 콜로니 수.")
    image: str = Field(description="검출 표시 이미지 base64 (PNG). 좌표는 담기지 않는다.")
