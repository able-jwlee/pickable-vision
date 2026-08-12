"""분리·색 축 기본값을 실측 최적점에 고정한다.

세 값 모두 2026-08-12 에 현재 설정에서 재측정했다. 이전 곡선은
candidate_source="union" 도입 전 기준이라 무효였다. 기본값이 조용히
움직이면 성적이 내려가므로 상수로 묶는다.
"""
from app import config


def test_split_area_ratio_default_is_the_measured_optimum():
    """1.5 가 전역 F1 최고점이다 (78.80).

    실측: 0.8 → 78.29, 1.0 → 78.31, 1.2 → 78.58, **1.5 → 78.80**,
    2.0 → 77.90, 3.0 → 77.80, watershed 끔 → 77.87.
    양쪽으로 내려가는 진짜 봉우리다.
    """
    assert config.BLOB_SPLIT_AREA_RATIO == 1.5


def test_watershed_split_stays_on():
    """끄면 재현율이 75.7% → 71.1% 로 내려간다 (F1 78.80 → 77.87)."""
    assert config.BLOB_WATERSHED_SPLIT is True


def test_colour_credit_stays_off():
    """현재 설정에서는 켜면 네 그룹 전부 나빠진다.

    2배에서 정밀도 82.20% → 59.82%, F1 78.80 → 68.14.
    그룹별 F1: lower 83.2→67.3, bright 80.7→74.6, dark 83.7→70.0,
    vague 61.6→52.7. "vague 26.1→40.9" 는 union 도입 이전 수치이며, 그
    이득은 이미 후보 생성이 가져갔다 (경위는 docs/detection_parameters.md 참조).
    """
    assert config.BLOB_COLOUR_CREDIT_MAX == 1.0
