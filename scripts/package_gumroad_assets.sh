#!/usr/bin/env bash
# Build Gumroad-ready zip bundles from the SIGMA monorepo.
#
# Outputs:
#   dist/gumroad/dashboard-template.zip  - Next.js dashboard shell + components
#   dist/gumroad/ml-boilerplate.zip      - FastAPI ML signal pipeline
#
# Usage:
#   bash scripts/package_gumroad_assets.sh
#
# Each bundle includes a README.md explaining what is and isn't in the box.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/dist/gumroad"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

mkdir -p "${OUT_DIR}"

build_dashboard_template() {
  local stage="${WORK_DIR}/dashboard-template"
  rm -rf "${stage}"
  mkdir -p "${stage}/app" "${stage}/components" "${stage}/lib" "${stage}/hooks"

  cp -r "${REPO_ROOT}/apps/web/app/(dashboard)" "${stage}/app/"
  cp -r "${REPO_ROOT}/apps/web/components/layout" "${stage}/components/"
  cp -r "${REPO_ROOT}/apps/web/components/billing" "${stage}/components/"
  cp -r "${REPO_ROOT}/apps/web/components/signals" "${stage}/components/"
  cp -r "${REPO_ROOT}/apps/web/components/portfolio" "${stage}/components/"
  cp "${REPO_ROOT}/apps/web/lib/api.ts" "${stage}/lib/"
  cp "${REPO_ROOT}/apps/web/lib/utils.ts" "${stage}/lib/" 2>/dev/null || true
  cp "${REPO_ROOT}/apps/web/hooks/"*.ts "${stage}/hooks/" 2>/dev/null || true
  cp "${REPO_ROOT}/apps/web/tailwind.config.ts" "${stage}/" 2>/dev/null || true

  cat > "${stage}/README.md" <<'EOF'
# SIGMA Dashboard Template

A polished Next.js 16 (App Router) + Tailwind dashboard shell with billing, API key,
signal explorer, and portfolio screens. Drop into any project that uses Clerk for auth.

## What's included

- `app/(dashboard)/` route group with overview, signals, API keys, billing, portfolio
- `components/layout/` Sidebar + Header
- `components/{billing,signals,portfolio}/` reusable building blocks
- `lib/api.ts` typed REST wrappers and `hooks/` SWR hooks

## What's not included

- Authentication setup (assumes Clerk is configured at the app level)
- Backend API (this is UI only - bring your own REST endpoints)
- Stripe wiring
- Project bootstrap (you provide `package.json`, `next.config.ts`, etc.)

## License

Single-project commercial use. See LICENSE.txt.
EOF

  cat > "${stage}/LICENSE.txt" <<'EOF'
Copyright (c) SIGMA. Single-project commercial license.
You may use this template in one production project per purchased seat.
Redistribution or reselling of the source files is not permitted.
EOF

  (cd "${WORK_DIR}" && zip -rq "${OUT_DIR}/dashboard-template.zip" "dashboard-template")
  echo "wrote ${OUT_DIR}/dashboard-template.zip"
}

build_ml_boilerplate() {
  local stage="${WORK_DIR}/ml-boilerplate"
  rm -rf "${stage}"
  mkdir -p "${stage}/ml" "${stage}/quantum"

  cp -r "${REPO_ROOT}/apps/api/ml/." "${stage}/ml/"
  cp -r "${REPO_ROOT}/apps/api/quantum/." "${stage}/quantum/"

  cat > "${stage}/requirements-ml.txt" <<'EOF'
fastapi>=0.110
pandas
numpy
httpx
pandas-ta
scikit-learn
xgboost
joblib
torch
pennylane
cvxpy
transformers
EOF

  cat > "${stage}/README.md" <<'EOF'
# SIGMA ML + Quantum Boilerplate

Production-ready Python signal pipeline lifted straight from SIGMA. Includes the
ensemble model, LSTM, quantum-hybrid model, sentiment hooks, and the QAOA portfolio
optimizer.

## What's included

- `ml/` data fetch, feature engineering, model loading + inference
- `ml/models/` ensemble (RF + XGBoost), LSTM, quantum-hybrid (QSVC) models
- `ml/sentiment.py` FinBERT integration (lazy loaded)
- `quantum/` PennyLane QAOA circuits, QUBO solver, and portfolio optimizer

## What's not included

- FastAPI app, routers, auth, or DB schema (this is the ML core only)
- Trained model weights
- Dataset

## How to use

```bash
pip install -r requirements-ml.txt
python -c "from ml.pipeline import run_signal_pipeline; print(run_signal_pipeline('AAPL'))"
```

## License

Single-project commercial use. See LICENSE.txt.
EOF

  cat > "${stage}/LICENSE.txt" <<'EOF'
Copyright (c) SIGMA. Single-project commercial license.
You may use this code in one production project per purchased seat.
Redistribution or reselling of the source files is not permitted.
EOF

  (cd "${WORK_DIR}" && zip -rq "${OUT_DIR}/ml-boilerplate.zip" "ml-boilerplate")
  echo "wrote ${OUT_DIR}/ml-boilerplate.zip"
}

build_dashboard_template
build_ml_boilerplate

echo
echo "Done. Upload the contents of ${OUT_DIR} to Gumroad, then set"
echo "  NEXT_PUBLIC_GUMROAD_DASHBOARD_URL"
echo "  NEXT_PUBLIC_GUMROAD_ML_URL"
echo "in your prod env so the landing page surfaces them."
