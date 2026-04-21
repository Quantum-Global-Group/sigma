# SIGMA — Tech Stack Priority Tiers

> **Rule:** Ship with Essential only. Add Core by Week 4. Nice-to-have when revenue hits. Pursue Later when scaling.

---

## Tier 1 — Essential (Week 1, Day 1)

These block everything else. Don't write a line of product code without these in place.

### Languages
| Tool | Version | Role |
|------|---------|------|
| TypeScript | 5.x | Frontend + API gateway |
| Python | 3.11+ | ML, signals, quantum, FastAPI backend |

### Dev Environment
| Tool | Role | Why Now |
|------|------|---------|
| Cursor | Primary IDE | AI-assisted code gen — you already use this |
| GitHub | Version control | CI/CD via Actions — already in use |
| Docker + Compose | Local dev orchestration | Mirrors prod exactly — already in your stack |

### Frontend
| Tool | Role | Why Now |
|------|------|---------|
| Next.js 15 | Full-stack React framework | Landing page, dashboard, docs, pricing |
| React 19 | UI layer | Server Components reduce bundle size |
| Tailwind CSS | Styling | You already use this — zero learning curve |

### Backend
| Tool | Role | Why Now |
|------|------|---------|
| FastAPI | Python API — signals, ML, quantum | Your primary backend framework |
| Pydantic v2 | Data validation + serialization | Built into FastAPI — pin explicitly |

### Data
| Tool | Role | Why Now |
|------|------|---------|
| PostgreSQL 15 | Primary database | Users, keys, usage logs, billing events |
| Redis 7 | Cache + rate limiting | API key lookup, 60-min signal cache |

### Monetization + Auth
| Tool | Role | Why Now |
|------|------|---------|
| Stripe Billing | Usage metering + subscriptions | Revenue — wire this before any users |
| Clerk | Auth — email, GitHub OAuth, API keys | Saves 20+ hours vs rolling your own |
| Gumroad / LemonSqueezy | Digital product sales | Upload zip → payment link → sell today |

### Deployment
| Tool | Role | Why Now |
|------|------|---------|
| Vercel | Frontend + serverless functions | Auto-deploy on push — free tier sufficient |
| Railway | FastAPI + Postgres + Redis hosting | One-command deploy, mirrors Docker Compose |

---

## Tier 2 — Core (Week 2–4)

Add these once the skeleton is deployed and your first endpoint is live.

### ML / Signals
| Tool | Role | Notes |
|------|------|-------|
| yfinance | Free OHLCV market data | Stocks, ETFs, crypto — zero cost |
| pandas-ta | 130+ technical indicators | RSI, MACD, Bollinger, ATR in one line each |
| PyTorch | Model training + inference | LSTM, Transformer, ensemble models |
| scikit-learn | Classical ML + feature pipelines | Faster iteration than PyTorch for non-neural |
| CVXPY | Portfolio optimization | Convex solver — classical fallback to quantum |
| Qiskit | Quantum algorithm backend | QUBO, QAOA — your defensible moat |
| PennyLane | Hybrid quantum-classical ML | VQE, variational circuits |

### Data
| Tool | Role | Notes |
|------|------|-------|
| TimescaleDB | Time-series PostgreSQL extension | Drop-in — 10–100x faster range queries on signal history |

### Frontend Components
| Tool | Role | Notes |
|------|------|-------|
| shadcn/ui | Production-grade component library | Tables, dialogs, command palettes — built on Radix + Tailwind |
| Recharts | Data visualization | Signal charts, portfolio curves, API usage graphs |

### Observability
| Tool | Role | Notes |
|------|------|-------|
| Sentry | Error tracking | Free tier: 5k errors/month — one SDK call on startup |
| Langfuse | ML pipeline tracing | End-to-end trace: fetch → features → inference → response |
| pytest | Unit + integration testing | Run in GitHub Actions on every push |

---

## Tier 3 — Nice to Have (Month 2–3, post first revenue)

Add when you have paying users and need to improve retention or conversion.

| Tool | Role | Trigger to Add |
|------|------|---------------|
| HuggingFace Transformers | FinBERT sentiment analysis for signals | When you want NLP features in signal pipeline |
| hypothesis | Property-based testing | When test coverage becomes a concern |
| PostHog | Product analytics — funnels, retention | When you need conversion data beyond Stripe |
| Replicate | Host + monetize trained models per-inference | When you want passive inference revenue |
| Upstash | Serverless Redis (cheaper at scale) | When Railway Redis bill exceeds $30/mo |

---

## Tier 4 — Pursue Later (Month 4+, scaling phase)

Do not touch these until you have consistent MRR and real scaling pressure.

| Tool | Role | When |
|------|------|------|
| LangGraph | Multi-step signal pipeline orchestration | When signal chains exceed 3 hops |
| AWS Lambda | Cheaper compute at high call volume | When Railway exceeds $100/mo |
| Rust + PyO3 | Performance-critical signal paths | When latency < 100ms becomes a requirement |
| ChromaDB | Semantic search over signals | When you add "find similar signals" feature |
| Kubernetes | Container orchestration | When you have 10+ services and a DevOps budget |
| GraphQL | Flexible API query layer | Never for MVP — REST is fine at this scale |
| Temporal | Durable workflow execution | When you have complex multi-day job pipelines |

---

## What You Are Explicitly Not Using (and Why)

| Tool | Reason to Skip |
|------|---------------|
| MongoDB | You know Postgres — it handles JSON columns natively, no reason to switch |
| Redux | React Server Components + useState is sufficient for this dashboard |
| Next Auth | Clerk does more in less time — API key management UI included |
| Celery | APScheduler embedded in FastAPI is enough for scheduled retraining at this scale |
| Kubernetes | Railway handles orchestration — k8s is overhead without an ops team |
| GraphQL | REST endpoints are simpler, faster to ship, easier to document |

---

## Stack Summary (One Line Per Layer)

```
IDE:         Cursor + VS Code + Claude Code CLI
Languages:   TypeScript (frontend/gateway) + Python 3.11 (ML/backend)
Frontend:    Next.js 15 + React 19 + Tailwind + shadcn/ui + Recharts
Gateway:     Vercel Functions (TypeScript, auth + billing)
Backend:     FastAPI + Pydantic v2 (Python, signals + ML + quantum)
ML Core:     PyTorch + scikit-learn + yfinance + pandas-ta + CVXPY
Quantum:     Qiskit + PennyLane (your moat)
Data:        PostgreSQL + TimescaleDB + Redis
Auth:        Clerk
Payments:    Stripe Billing (metering + subscriptions) + Gumroad (digital products)
Deploy:      Vercel (frontend) + Railway (backend + DB)
Monitoring:  Sentry + Langfuse + pytest
```
