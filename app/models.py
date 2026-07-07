from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app import config


class DetectRequest(BaseModel):
    # 이미지 입력: base64(image) 또는 로컬 경로(image_path) 중 하나.
    # image_path는 로컬 튜닝 편의용 — 서버와 파일시스템을 공유할 때만 동작.
    image: str | None = None
    image_path: str | None = None
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
    # 표시(저장/프리뷰 이미지) 모드:
    #   "all"  → 검출 전체를 붉은 원으로 (카운트/분석용, 기본)
    #   "pick" → 피킹 대상(pickable)만 초록 원으로 (로봇이 실제 집을 안전 후보만)
    # 어느 쪽이든 응답 JSON의 colonies/pickable/score는 동일하게 전부 반환된다.
    annotate: Literal["all", "pick"] = "all"

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
    width: int
    height: int
    count: int
    colonies: list[Colony]
    # save_annotated=true일 때 저장된 이미지 경로, 아니면 null
    annotated_path: str | None = None


class PreviewResponse(BaseModel):
    count: int
    image: str
