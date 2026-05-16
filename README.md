# Deribit Trading Agent

[English](./README.md) · [中文](./README_CN.md)

A personal **derivatives trading terminal** for Deribit, with a built-in **AI copilot named Vida** that streams answers about live markets, your portfolio, and option strategies — and, when you let her, places orders for you behind a one-click confirmation card.

![Dashboard with AI assistant](assets/screenshots/dashboard.png)

---

## What you get

A clean, single-screen trading workstation for BTC and ETH perps, futures, and the full options chain on Deribit — with a streaming AI assistant docked on the right that can actually *do* things, not just chat.

- **Live multi-instrument dashboard** — perps, futures, full option chain with Greeks, IV surface, equity curve.
- **Smart orders** — tick-chaser and intent-router execution algos with maker-preferred fills and adjustable patience.
- **Portfolio + risk** — positions, P&L attribution, daily-loss limits, margin ratios.
- **Multi-account** — manage several Deribit accounts from one install. The top-right chip switches the active account; each account keeps its own portfolio, chat history, AI-trading toggle, and audit trail. Credentials are Fernet-encrypted locally and never leave your machine.
- **Vida, your AI trading copilot** — streaming chat with 13 atomic market/account tools, 4 gated trading tools, and per-call confirmation cards for every write action.

**Option chain — IV smile + term structure side by side:**

![Option chain page](assets/screenshots/options.png)

**Futures — chart, smart-order panel, live order book:**

![Futures page](assets/screenshots/futures.png)

---

## What Vida can do for you

Vida is an OpenAI-compatible LLM (defaults to DeepSeek; works with Zhipu GLM, OpenAI, vLLM, ollama, anything OpenAI-API-compatible) running a streaming ReAct loop over a hand-curated tool set.

**Ask her about the market or your account** — always read-only, always anchored on live tool data:

- *"What's the BTC perp price?"* → single-instrument quote with funding + 24h change.
- *"Show me the ETH option market."* → one batch call returns the entire chain with IVs / volumes / OI.
- *"What's nearest expiry, and what does the IV smile look like?"* → expiry list + per-strike IVs.
- *"Build me a 70k–80k BTC call spread for 27JUN26 — payoff and Greeks."* → multi-leg payoff curve + aggregate Greeks via `analyze_option_combo`.
- *"What's driving today's P&L? Am I near my daily loss limit?"* → positions, P&L breakdown, risk status.

**Let her trade for you (opt-in)** — every write call pops a confirmation card:

1. In Settings, flip **AI Trading** on for the active account. The chat header lock-icon turns into an unlock.
2. Ask Vida something like *"Place a limit buy for 10 BTC-PERPETUAL at $58,000."*
3. Vida echoes the parameters and calls `place_order`. The agent loop pauses and the UI renders a **ConfirmationCard** with a clean order ticket and a 30-second countdown.
4. Click **Confirm** → the order submits. Click **Cancel** (or let it time out) → the tool returns an error to Vida and she adjusts her plan.

Vida has access to:
- `place_order`, `cancel_order`, `smart_order`, `cancel_smart_order` — all gated by the confirmation card.
- Every successful or declined write call is recorded in a local audit log.

She will **refuse to predict price direction** or give direct buy/sell calls — she presents trade-offs, payoffs, Greeks, and what would invalidate an idea.

---

## Get started

### 1. Get a Deribit account

If you don't have one yet, sign up using my referral link:

👉 **[https://www.deribit.com/?reg=20899.657](https://www.deribit.com/?reg=20899.657)**

Then create an API key:

1. Log in → **Account → API**.
2. Click **Add new key**, give it a label (e.g. `vida-local`), and enable the scopes you want: `trade:read_write`, `account:read`, `wallet:read`.
3. Copy the **Client ID** and **Client Secret** — you'll paste them into the app in step 4.
4. **Start on testnet first.** Same registration link, but log in at [test.deribit.com](https://test.deribit.com/) and generate a separate testnet key. The app defaults to testnet and requires an explicit toggle in Settings to switch to production.

### 2. Run the backend

```bash
git clone https://github.com/ipatpat/deribit-trading.git
cd deribit-trading
uv sync
export DEEPSEEK_API_KEY=sk-...      # or OPENAI_API_KEY / ZHIPU_API_KEY, etc.
uv run python -m deribit_trading api --env testnet --host 127.0.0.1 --port 8000
```

### 3. Run the frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

### 4. Add your Deribit account

1. Open `http://localhost:5173`. The app will prompt you to add an account on first launch.
2. **Settings → Account Configuration → Add Account**: paste the Client ID + Client Secret from step 1, pick `testnet`, save.
3. The top-right chip will switch to the new account once it connects.

### 5. Talk to Vida

1. Click the floating chat button (bottom-right) to open the sidebar.
2. Try one of the suggested prompts, or ask *"What's the BTC perp price?"*.
3. To enable trading: **Settings → AI Trading → On** for this account, then ask her to place a small testnet order. Confirm the card to actually submit.

---

## Tech stack

| Layer | Tech |
| --- | --- |
| Trading core | Python 3.12, `asyncio`, `pydantic`, `websockets`, Deribit JSON-RPC v2 |
| Persistence | SQLite (`aiosqlite`), bucketed equity snapshots, candle cache, write-call audit log |
| REST API | FastAPI + SSE streaming |
| MCP | Python `mcp` SDK (13 atomic data tools + 4 gated write tools) |
| LLM client | `openai` SDK (any OpenAI-compatible endpoint) |
| Frontend | React 18, TypeScript, Vite, Tailwind, Zustand, Radix UI, ECharts |
| Testing | `pytest`, `vitest` |

---

## Design notes (for the curious)

A few opinions baked into the design:

- **Atomic data plane, not API wrappers.** Each MCP tool is a *minimal data unit*. Complex analysis (IV skew, term structure, payoff sweeps) belongs in a future Skill layer that *composes* these tools — keeping the agent surface thin and the LLM in charge of reasoning over raw arrays.
- **Just-in-time disclosure.** Tier 1 knowledge (~800 tokens) only covers what the agent *must know to use the tools*. Fee schedules, smart-order internals, etc. are fetched on demand via `get_system_status`, not preloaded into every prompt.
- **No "interpretation" fields in MCP responses.** Tools return numbers; the LLM decides what they mean. No `"shape": "contango"` magic strings.
- **No hidden caching.** All tool calls hit Deribit live. The batch endpoint is ~200ms — caching complexity isn't worth it.
- **Confirmation cards over autonomous trading.** Vida can call write tools, but every single call is intercepted by a 30-second per-call confirmation card. No bulk approval, no "remember this", no autopilot.
- **Refuse price predictions and direct buy/sell calls.** Trade-offs, payoffs, risks — not "BTC will go up."

---

## License

[MIT](./LICENSE) — do what you want, but don't blame me if you lose money. This is a research tool, not investment advice.

---

## Acknowledgements

Built with [Claude Code](https://claude.com/claude-code) as a pair-programming partner, including the OpenSpec-style change planning workflow.
