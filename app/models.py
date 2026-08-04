from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app import config


class DetectRequest(BaseModel):
    # 이미지 입력: base64(image) 또는 로컬 경로(image_path) 중 하나.
    # image_path는 로컬 튜닝 편의용 — 서버와 파일시스템을 공유할 때만 동작.
    image: str | None = None
    image_path: str | None = None
    # 검출 경로 선택.
    #   "blob"   → app/blob_detector.py (기본). 원형 petri 접시 기준으로 튜닝.
    #              라벨 40장 측정에서 tophat의 정밀도 1.2%/재현율 23.8%를
    #              90.9%/49.6%로 올렸다.
    #   "tophat" → 기존 app/detector.py 경로. 4×2 몰딩 8웰 플레이트
    #              (tests/fixtures/agar_sample.jpg)에 맞게 튜닝돼 있다.
    #              그 포맷은 정답 라벨이 없어 blob 경로를 검증할 수 없으므로,
    #              8웰 플레이트를 쓸 때는 이 경로를 명시하는 편이 안전하다.
    # tophat 전용 knob(invert, tophat_kernel, threshold_offset, min_area, max_area,
    # min_circularity, mask_walls, split_touching)은 method="blob"에서 무시된다.
    method: Literal["blob", "tophat"] = "blob"
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
    min_area: float = Field(config.DEFAULT_MIN_AREA, ge=0.0)
    max_area: float = Field(config.DEFAULT_MAX_AREA, gt=0.0)
    min_circularity: float = Field(config.DEFAULT_MIN_CIRCULARITY, ge=0.0, le=1.0)
    invert: bool = config.DEFAULT_INVERT
    tophat_kernel: int = config.DEFAULT_TOPHAT_KERNEL
    # 민감도: 높일수록(양수) 임계값↓ → 흐린/작은 콜로니까지 더 잡음(노이즈↑),
    # 낮추면(음수) 엄격. 유효 sweet spot 대략 -4~+10 (그 밖은 뭉침/노이즈).
    threshold_offset: int = Field(config.DEFAULT_THRESHOLD_OFFSET, ge=-50, le=50)
    mask_walls: bool = config.DEFAULT_MASK_WALLS
    # true면 붙은 콜로니를 watershed로 분리(밀집 구간 재현율↑, 과분할 위험). 기본 on.
    split_touching: bool = config.DEFAULT_SPLIT_TOUCHING
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

    # 오퍼레이터용 0~100 추상 스케일 (스펙 §4.2). 있으면 대응하는 raw 필드보다 우선.
    # None이면 기존 raw 필드(threshold_offset, min_area, max_area) 또는 config default를 사용.
    sensitivity: int | None = Field(None, ge=0, le=100)
    min_size:    int | None = Field(None, ge=0, le=100)
    max_size:    int | None = Field(None, ge=0, le=100)
    edge_margin: int | None = Field(None, ge=0, le=100)

    @field_validator("tophat_kernel")
    @classmethod
    def _tophat_kernel_min(cls, v: int) -> int:
        if v < 3:
            raise ValueError("tophat_kernel must be >= 3")
        return v

    @model_validator(mode="after")
    def _require_one_source(self) -> "DetectRequest":
        if not self.image and not self.image_path:
            raise ValueError(
                "either 'image' (base64) or 'image_path' must be provided"
            )
        return self

    @model_validator(mode="after")
    def _area_range_ordered(self) -> "DetectRequest":
        if self.min_area >= self.max_area:
            raise ValueError("min_area must be < max_area")
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
