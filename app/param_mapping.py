"""오퍼레이터용 0~100 스케일 → CV 원본값 매핑.

각 함수는 슬라이더 값(0~100)을 받아 검출기 내부 파라미터로 변환한다.
스펙 §4.2 매핑 표의 앵커값을 만족하도록 설계됨.
"""
import math


def sensitivity_to_offset(v: int) -> int:
    """감도 0~100 → threshold_offset. 50이 현재 default(+7)에 앵커.

    0~50 구간 linear: -3 → +7
    50~100 구간 linear: +7 → +15
    """
    if v <= 50:
        return round(-3 + (v / 50) * 10)
    return round(7 + ((v - 50) / 50) * 8)


def min_size_to_area(v: int) -> float:
    """최소 크기 0~100 → min_area. 20이 현재 default(≈6)에 앵커.

    r_min = 1 + (v/100)² · 9  (비선형 — 슬라이더 앞부분에서 세밀 조정)
    min_area = π · r_min²
    """
    r = 1 + (v / 100) ** 2 * 9
    return math.pi * r * r


def max_size_to_area(v: int) -> float:
    """최대 크기 0~100 → max_area. 80이 현재 default(≈5000)에 앵커.

    r_max = 10 + (v/100) · 40  (linear)
    max_area = π · r_max²
    """
    r = 10 + (v / 100) * 40
    return math.pi * r * r


def edge_to_margin_px(v: int) -> int:
    """벽 여백 0~100 → 픽셀. 40이 현재 default(60px)에 앵커.

    edge_margin = v · 1.5  (linear, 0~150px)
    """
    return round(v * 1.5)
