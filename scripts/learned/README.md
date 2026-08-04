# 학습 기반 후보 판정기 — 실험 코드

`app/blob_detector.py`의 수작업 게이트(t-통계량 + 색 + 모양의 AND 사슬)를
학습된 판정 경계로 대체할 수 있는지 검증한 코드다.

**결론: 피킹 용도에서는 기각.** 같은 정밀도(89~90%)에서 학습 모델의 재현율이
낮았다(43% 대 51%). 다만 **CFU 계수 용도라면 GBM이 낫다** — F1 정점이
65.4 → 67.0이다. 자세한 수치와 해석은
[`docs/detection-improvement-2026-07-28.md`](../../docs/detection-improvement-2026-07-28.md) §8.6.

## 왜 남겨두는가

용도가 카운팅으로 바뀌면 바로 쓸 수 있고, 특징을 추가했을 때 재평가하는
비용이 거의 없다. 런타임 의존성은 늘리지 않는다 — 로지스틱 회귀와
히스토그램 기반 경사부스팅을 numpy로 직접 구현했으므로, 채택하더라도
계수/트리 JSON만 배포하면 된다.

## 실행 순서

```bash
# 1) 후보 특징 추출 (output/learned/cands.npz)
.venv/Scripts/python scripts/learned/extract_features.py

# 2) 로지스틱 회귀 — 후보 단위 성적 + 계수 저장
.venv/Scripts/python scripts/learned/train_logreg.py

# 3) 로지스틱 회귀 — 콜로니 단위 성적 (NMS·매칭 포함)
.venv/Scripts/python scripts/learned/eval_logreg.py

# 4) 경사부스팅 — 콜로니 단위 성적
.venv/Scripts/python scripts/learned/eval_gbm.py
```

`sample/` 디렉터리(이미지 + 같은 이름의 라벨 JSON)가 필요하다.

## 검증 규칙 — 반드시 지킬 것

**이미지 단위 5-fold, 촬영조건별 층화.** 같은 접시의 콜로니는 조명·배지·균주를
공유하므로 콜로니 단위로 나누면 검증이 무의미해진다. 표준화 통계와 계수/트리는
학습 fold 에서만 구한다.

**콜로니 단위로 평가할 것.** 후보 단위 지표는 오해를 부른다 — 콜로니 하나에
후보가 평균 20여 개 붙고 그중 하나만 살아남으면 검출 성공이므로, 후보 재현율
5.2%가 콜로니 재현율 51%에 대응한다. 실제로 후보 단위로만 보면 학습 판정기가
이기는 것처럼 보였지만, NMS와 1:1 매칭을 거치면 결과가 뒤집혔다.

## 파일

| 파일 | 역할 |
|---|---|
| `extract_features.py` | 후보별 특징 16개 + 라벨 추출 → `output/learned/cands.npz` |
| `train_logreg.py` | numpy 로지스틱 회귀 (L2, 클래스 가중), 계수 JSON 저장 |
| `eval_logreg.py` | 콜로니 단위 평가 + 정답 박스 복원 + NMS/매칭 유틸 |
| `gbm.py` | 히스토그램 기반 경사부스팅 (XGBoost 식 뉴턴 부스팅) |
| `eval_gbm.py` | GBM 콜로니 단위 평가 |
