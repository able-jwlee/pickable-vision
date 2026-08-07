from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app import config


class DetectRequest(BaseModel):
    # 이미지 입력: base64(image) 또는 로컬 경로(image_path) 중 하나.
    # image_path는 로컬 튜닝 편의용 — 서버와 파일시스템을 공유할 때만 동작.
    image: str | None = None
    image_path: str | None = None
    # 콜로니가 한천보다 밝은지 어두운지. 오퍼레이터가 눈으로 판단할 수 있다.
    #   "auto" → 양극성 모두 검출 후 병합 (기본, 안전)
    #   "bright"/"dark" → 그 극성만 본다
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
    polarity: Literal["auto", "both", "bright", "dark"] = "auto"
    # blob 경로의 플레이트 기하구조. 자동 판정은 판별력이 없어(blob_detector의
    # plate_roi docstring 참조) 호출자가 명시한다.
    #   "petri" → 원형 접시. "well8" → 4×2 몰딩 8웰 플레이트.
    plate_type: Literal["petri", "well8"] = "petri"
    # ------------------------------------------------------------------
    # blob 경로 파라미터. 기본값은 sample/ 40장(정답 1,886개) 실측 최적값이고,
    # 각 필드의 실측 곡선은 app/config.py 주석에 기록돼 있다.
    # 이미지마다 조절할 필요가 있는 것만 노출한다 — 밝기·콜로니 극성(밝은지
    # 어두운지)·접시 위치와 크기는 알고리즘이 자동 처리하므로 knob이 없다.
    # ------------------------------------------------------------------
    # 감도. 면적 가중 t-통계량 하한 — 낮추면 흐린 콜로니까지 잡고(재현율↑)
    # 오검출이 늘어난다. None이면 sensitivity(0~100) 매핑, 그것도 없으면 기본값.
    # 실측: 12 → 정밀도 50.1%/재현율 63.6%,  25 → 78.3%/55.0%,
    #       35 → 90.9%/49.6% (기본값),      60 → 98.6%/34.1%
    min_t: float | None = Field(None, ge=1.0, le=200.0)
    # 콜로니 크기 창 — 지름 ÷ 접시 지름. 0 = 제한 없음(기본값).
    # 비율이라 해상도·카메라와 무관하다. 실측 분포: 1.2%~45%, 중앙값 7%.
    min_diam_frac: float = Field(config.BLOB_MIN_DIAM_FRAC, ge=0.0, le=1.0)
    max_diam_frac: float = Field(config.BLOB_MAX_DIAM_FRAC, ge=0.0, le=1.0)
    # 색이 뚜렷하면 감도 요구치를 이 배율까지 깎아준다. 1.0 = 끔(기본값).
    # 재현율을 크게 올리지만 정밀도를 그만큼 내준다. 이미지 종류별로 최적이
    # 갈린다 — 실측 2배에서 vague는 F1 26.1→40.9, lower-res는 77.6→61.6.
    colour_credit: float = Field(config.BLOB_COLOUR_CREDIT_MAX, ge=1.0, le=8.0)
    # 처리 해상도(최대변 px). 콜로니당 픽셀 수가 t-통계량을 좌우한다.
    # 실측: 1024가 전체 최적, 1536은 콜로니가 작은 이미지에만 유리, 2048은 전부 나쁨.
    work_size: int = Field(config.BLOB_WORK_SIZE, ge=384, le=2048)
    # 후보 생성 방식.
    #   "union"(기본) = LoG ∪ 이진화. 실측상 전 구간에서 LoG 단독보다
    #                   +2.9~3.5%p 위다 — 두 방식이 서로 다른 것을 보기 때문.
    #   "log"       = LoG 단독 (구동작).
    #   "threshold" = 이진화 단독. 정밀도 93% 이상 구간에서는 이쪽이 합집합보다
    #                 낫다(94%에서 67.3% 대 62.9%) — 계수(CFU) 용도에 적합.
    candidate_source: Literal["union", "log", "threshold"] = (
        config.BLOB_CANDIDATE_SOURCE)
    # 이진화 후보의 임계값 레벨 수. 12/24/36 에서 재현율 67.9/70.8/71.3% 로
    # 24 에서 포화한다. 늘려도 커버리지 천장(~90%)은 안 오른다.
    threshold_levels: int = Field(config.BLOB_THRESHOLD_LEVELS, ge=2, le=64)
    # 둘레 기반 원형도 4πA/P². **기본 0 = 끔.** 경계 거칠기에 극도로 민감해
    # 합집합 후보(이진화 성분은 둘레가 거칠다)를 부당하게 버렸다. 모양 판정은
    # min_roundness(면적 기반)가 담당한다.
    min_circularity: float = Field(config.BLOB_MIN_CIRCULARITY, ge=0.0, le=1.0)
    # 채움율 A/(bounding box 면적). 0.60 으로 올리면 정밀도 92~96% 구간에서
    # +1.4~2.1%p — 계수 용도처럼 정밀도가 중요할 때 쓴다.
    min_fill: float = Field(config.BLOB_MIN_FILL, ge=0.0, le=1.0)
    # 분리 — 붙은 콜로니를 거리변환 watershed 로 나눈다.
    #   watershed_split  끄면 뭉친 군집이 하나로 검출된다. **끄면 나빠지기만 한다**
    #                    (실측: 한 접시에서 맞힘 7개 감소). 이상하게 잘릴 때만 끄는
    #                    비상구이지 조정 knob 이 아니다.
    #   split_area_ratio 자연 윤곽 면적이 기대 면적의 이 배를 넘으면 병합으로 본다.
    #                    낮출수록 적극적으로 나눈다.
    watershed_split: bool = config.BLOB_WATERSHED_SPLIT
    split_area_ratio: float = Field(config.BLOB_SPLIT_AREA_RATIO, ge=0.5, le=5.0)
    # 모양 게이트. 재현율을 더 짜내야 할 때 접시별로 푸는 용도이고, 기본값이
    # 이미 실측 최적이라 보통은 건드릴 필요가 없다.
    #   min_solidity  면적 ÷ convex hull 면적. 오목한 얼룩·긁힘 배제.
    #                 0.75 아래로는 결과가 변하지 않는다(포화).
    #   min_roundness 면적 ÷ 최소외접원 면적. 주된 모양 판정.
    #                 **완화를 권하지 않는다** — 같은 정밀도에서 감도(min_t)를
    #                 내리는 쪽이 더 많이 맞힌다(실측 70.3% 대 72.9%).
    # 0 = 해당 게이트 끔.
    min_solidity: float = Field(config.BLOB_MIN_SOLIDITY, ge=0.0, le=1.0)
    min_roundness: float = Field(config.BLOB_MIN_ROUNDNESS, ge=0.0, le=1.0)
    # true면 1차 검출로 콜로니 크기를 재고 해상도를 자동 조정해 재검출한다
    # (검출 비용 약 2배). 기본 끔 — 실측에서 전체 F1이 오히려 떨어졌다
    # (config.BLOB_ADAPTIVE_SCALE 주석 참조). 해상도는 work_size로 지정할 것.
    adaptive_scale: bool = config.BLOB_ADAPTIVE_SCALE

    # ------------------------------------------------------------------
    # 피킹 후보 판정 — 검출된 콜로니 중 로봇이 실제로 집을 것을 고른다.
    # 두 경로 공통. 반지름 단위는 원본 이미지 픽셀이므로 해상도가 다른 카메라로
    # 바꾸면 함께 조정해야 한다(기본값은 8웰 플레이트 기준으로 튜닝된 값이다).
    # ------------------------------------------------------------------
    pick_radius_min: float | None = Field(None, ge=0.0)
    pick_radius_max: float | None = Field(None, ge=0.0)
    # 웰/접시 경계에서 안쪽만 피킹 대상으로 인정할지. False = 경계 제한 없음.
    mask_walls: bool = config.DEFAULT_MASK_WALLS
    # 주어지면 피킹 후보(pickable) 중 점수 상위 N개만 후보로 남김 (예: 96핀 → 96)
    pick_top_n: int | None = None
    # true면 콜로니를 표시한 이미지를 vision/output/ 에 저장 (로컬 확인용)
    save_annotated: bool = False
    # true면 **응답에** 표시 이미지를 base64로 함께 담는다 (좌표와 한 번에).
    # /detect/preview 는 이미지만 주고 좌표를 주지 않으므로, 둘을 같이 받으려면
    # 이 플래그를 쓴다.
    return_image: bool = False
    # 응답 이미지 형식. 4000px급 원본을 PNG로 담으면 응답이 수십 MB가 된다.
    image_format: Literal["jpeg", "png"] = "jpeg"
    image_quality: int = Field(85, ge=30, le=100)   # jpeg 전용
    # 표시 마커 모양. "square"(기본) = 정사각 테두리, "circle" = 원.
    # 콜로니가 원형이라 원을 그리면 윤곽선과 겹쳐 구분이 어렵다 — 직선 테두리가
    # 한천 텍스처 위에서 훨씬 잘 보인다.
    marker: Literal["square", "circle"] = "square"
    # 응답 이미지 최대 폭(px). 0이면 원본 크기. 좌표는 항상 원본 픽셀 기준이며,
    # 축소된 경우 응답의 annotated_image_scale 을 곱해야 이미지 위 좌표가 된다.
    image_max_width: int = Field(1600, ge=0, le=8000)
    # 표시(저장/프리뷰 이미지) 모드:
    #   "all"  → 검출 전체를 붉은 원으로 (카운트/분석용, 기본)
    #   "pick" → 피킹 대상(pickable)만 초록 원으로 (로봇이 실제 집을 안전 후보만)
    # 어느 쪽이든 응답 JSON의 colonies/pickable/score는 동일하게 전부 반환된다.
    annotate: Literal["all", "pick"] = "all"

    # 오퍼레이터용 0~100 추상 스케일. 있으면 대응하는 raw 필드보다 우선.
    #   sensitivity → min_t (감도)
    #   edge_margin → 피킹 안전 여백(px)
    sensitivity: int | None = Field(None, ge=0, le=100)
    edge_margin: int | None = Field(None, ge=0, le=100)

    @model_validator(mode="after")
    def _require_one_source(self) -> "DetectRequest":
        if not self.image and not self.image_path:
            raise ValueError(
                "either 'image' (base64) or 'image_path' must be provided"
            )
        return self



class Colony(BaseModel):
    id: int
    x: float
    y: float
    radius: float
    circularity: float = 1.0  # 원형도 (0~1, 1에 가까울수록 원) — 피킹 품질 지표
    score: float = 0.0        # 피킹 적합도 (0~1)
    pickable: bool = False    # 피킹 후보 여부


class DetectResponse(BaseModel):
    # width/height 는 **원본 이미지** 크기이고, colonies 의 x/y/radius 도
    # 원본 픽셀 기준이다 (처리 해상도와 무관).
    width: int
    height: int
    count: int
    colonies: list[Colony]
    # save_annotated=true일 때 저장된 이미지 경로, 아니면 null
    annotated_path: str | None = None
    # return_image=true일 때 콜로니를 표시한 이미지의 base64, 아니면 null.
    # 좌표(colonies)와 함께 한 응답에 담긴다.
    annotated_image: str | None = None
    # annotated_image 가 원본 대비 몇 배로 축소됐는지. 좌표를 이미지 위에
    # 겹치려면 x/y/radius 에 이 값을 곱한다. 축소 안 했으면 1.0.
    annotated_image_scale: float = 1.0
    # 검출에 실제 적용된 raw 파라미터 dict (튜닝 재현·이슈 리포트용)
    applied_params: dict = {}


class PreviewResponse(BaseModel):
    count: int
    image: str
