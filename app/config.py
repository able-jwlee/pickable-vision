# 검출 기본 파라미터 (요청으로 override 가능)
# 목표: 재현율 우선 — 흐린/작은 콜로니까지 최대한 검출.
DEFAULT_MIN_AREA = 6.0         # 작은 콜로니 재현율↑ (튜닝: 8→6)
DEFAULT_MAX_AREA = 5000.0
DEFAULT_MIN_CIRCULARITY = 0.42 # 약간 찌그러진 콜로니도 통과 (튜닝: 0.45→0.42)
DEFAULT_INVERT = True          # 콜로니가 배경보다 어두우면 True (black top-hat)
DEFAULT_TOPHAT_KERNEL = 31     # top-hat 구조요소 크기(px). 콜로니보다 크게 잡아야 함
DEFAULT_MASK_WALLS = True      # 밝은 plate 내부(agar) ROI로 제한 → 프레임/벽/배경 제외

# 민감도 knob — Otsu 전역 임계값에서 이만큼 뺀다.
DEFAULT_THRESHOLD_OFFSET = 7   # >0 → 임계값↓ → 더 민감(흐린 것↑, 노이즈↑). <0 → 더 엄격.
                               # 유효 sweet spot 대략 -4 ~ +10 (그 밖은 뭉침/노이즈).
                               # 기본 +7: plate를 반듯하게 꽉 채워 찍는 조건에서 흐린 콜로니
                               # 재현율을 최대화한 값(샘플 튜닝). +8↑부터 노이즈 클러스터
                               # 발생, +10↑에서 임계값 바닥 닿아 질감까지 검출됨.

# 벽면 메니스커스(agar가 벽에 붙어 생기는 길고 얇은 어두운 주름) 제거.
# black-hat이 이 선형 그림자를 콜로니로 오검출 → watershed가 여러 조각으로 쪼갬.
# "길고(최대변≥LEN) 얇은(aspect≥ASPECT)" 연결성분만 제거. compact한 콜로니/클러스터는 보존.
MENISCUS_MIN_LEN = 80          # 실측: 메니스커스 최대변 170~326 vs 클러스터 ≤167
MENISCUS_MIN_ASPECT = 4.0      # 실측: 메니스커스 aspect 8~19 vs 클러스터 ≤2.8 (큰 간극)

# plate ROI 마스크 (밝은 agar 영역만 남김)
ROI_CLOSE_KERNEL = 35          # 콜로니 구멍을 메워 plate를 하나의 덩어리로
ROI_ERODE_KERNEL = 45          # 프레임/벽 경계에서 안쪽으로 크게 수축해 벽 오검출 방지
                               # (튜닝: 15→45. _well_mask에서 격자∩이 ROI로 바깥벽 제외)

# 8개 웰(덱) 격자 — plate를 규칙 격자로 나눠 웰 내부만 남기고 벽/프레임 제외.
# 하드웨어는 2행 × 4열 = 8덱(A1~B4). mask_walls=True일 때 이 격자로 검출을 제한.
WELL_ROWS = 2
WELL_COLS = 4
WELL_MARGIN = 40               # 각 웰 셀을 안쪽으로 줄이는 여백(px) — 벽/프레임 배제

# 붙은 콜로니 분리(watershed) — 기본 ON. 밀집 구간 재현율↑ (뭉친 콜로니 개별화).
# 가장자리 오검출이 조금 늘 수 있어, 필요 시 요청에서 split_touching:false로 끌 수 있음.
DEFAULT_SPLIT_TOUCHING = True
WATERSHED_MIN_DISTANCE = 5     # 씨앗(국소 최대) 간 최소 간격(px)
WATERSHED_SEED_MIN = 2.0       # 씨앗으로 인정할 최소 거리변환 값(px)

# 피킹 대상 선별(scoring) — 고립도 + 크기로 "집기 좋은" 콜로니 판정.
PICK_MIN_SEPARATION = 20.0     # 이웃 중심과 이 거리(px) 이상이어야 안전하게 집을 수 있음
PICK_ISOLATION_REF = 50.0      # 고립 점수 만점 기준 거리(px)
PICK_RADIUS_MIN = 3.0          # 너무 작으면(speck) 제외
PICK_RADIUS_MAX = 20.0         # 너무 크면(병합 추정) 제외
PICK_MIN_CIRCULARITY = 0.55    # 피킹 대상은 충분히 둥글어야 함(병합/균열/데브리 배제).
                               # 검출용(0.42)보다 엄격 — 로봇이 집을 건 단일 원형 콜로니만.
                               # 작은 콜로니는 픽셀 계단효과로 원형도가 낮게 나와, 0.55가
                               # 실측 분포(중앙값 0.59)상 "명확히 둥근 것"의 하한. 랭킹이 보완.
PICK_W_ISOLATION = 0.7         # 점수 가중치: 고립도
PICK_W_SIZE = 0.3              # 점수 가중치: 크기 적합도
# 피킹 안전 여백 — 웰/plate 경계에서 이만큼(px) 안쪽에 있는 것만 피킹 대상으로 인정.
# 벽 근처 반점/데브리를 pickable에서 제외해 "빈 곳/벽에 핀 찍기"를 방지. (검출 자체는 유지)
PICK_EDGE_MARGIN = 60          # well_mask ROI를 이 크기로 침식해 안전 내부만 남김

# 검출 결과 이미지 저장 (로컬 확인용)
OUTPUT_DIR = "output"          # vision/ 기준 상대 경로
DRAW_COLOR = (0, 0, 255)       # BGR 붉은색 (검출 콜로니 표시)
DRAW_PICK_COLOR = (0, 200, 0)  # BGR 초록색 (annotate="pick" 모드에서 피킹 대상 표시)
DRAW_THICKNESS = 2
MIN_DRAW_RADIUS = 3            # 작은 콜로니도 보이도록 최소 반지름
