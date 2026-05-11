# Deribit Trading Agent

[English](./README.md) · [中文](./README_CN.md)

一个个人用的 **衍生品交易终端**（Deribit），内置 **AI 助手**，可以流式回答关于实时行情、持仓组合、期权策略的问题。

![Dashboard with AI assistant](assets/screenshots/dashboard.png)

---

## 这个项目适合谁？

| 你是… | 你能得到什么 |
| --- | --- |
| **主观型衍生品交易员** | 一套干净的 Deribit 操作界面：实时永续/期权/期货行情、智能下单算法（tick 追价、意图路由）、组合与风控看板，外加一个可以问"给我看看 BTC 期权市场"的 LLM——不用再切来切去地点 tab。 |
| **AI 工程师 / Agent 设计师** | 一个 *渐进式披露* 在 MCP 工具设计中的完整范例：12 个原子化数据工具 + 1 个计算工具、类型自适应返回、精简系统提示词（约 800 tokens）、以及前端逐块渲染的 SSE 流式协议。完整实现可看 `src/deribit_trading/agent/` 和 `src/deribit_trading/mcp_server.py`。 |
| **衍生品初学者** | 一个安全的练习场：读取实时希腊值 / IV / 资金费率，用 `analyze_option_combo` 工具模拟多腿组合损益（跨式、铁鹰、备兑等），并让 AI 用大白话给你解释合约和策略。 |

---

## 它能做什么

### 交易终端（前端）
- **多品种实时看板**：BTC + ETH 永续、期货、含希腊值的完整期权链、隐波曲面、净值曲线。
- **智能下单**：tick 追价 + 意图路由算法，maker 优先成交，可调耐心度。
- **组合 + 风控视图**：持仓、盈亏归因、日亏损限额、保证金率。
- **设置**：分环境的凭据存储（Fernet 加密）、生产 / testnet 切换、自动刷新节奏调节。

**期权链——波动率微笑 + 期限结构并排显示：**

![Option chain page](assets/screenshots/options.png)

**期货——K 线图、智能下单面板、实时订单簿：**

![Futures page](assets/screenshots/futures.png)

### AI 助手（右侧聊天栏）
- **OpenAI 兼容 LLM**：默认 DeepSeek；同时支持智谱 GLM、OpenAI、vLLM、ollama 等任何 OpenAI-API 兼容端点。
- **13 个原子化 MCP 工具**：
  - 索引类——`list_instruments`、`list_expiries`
  - 单合约类——`get_quote`（类型自适应：永续 / 期权 / 期货）、`get_orderbook`、`get_candles`
  - 批量类——`get_market_snapshot`（一次约 200ms RTT 拉取整条期权链）
  - 账户类——`get_positions`、`get_balance`、`get_pnl_breakdown`、`get_risk_status`
  - 系统类——`get_system_status`
  - 计算类——`analyze_option_combo`（多腿损益曲线 + 净希腊值聚合）
- **SSE 流式协议**：text 增量、tool_use 生命周期事件、tool 结果、终态/错误事件——前端逐块实时渲染。每次工具调用都会渲染为一张可展开的卡片，可以查看入参 + 原始 JSON 输出。

---

## 技术栈

| 层 | 技术 |
| --- | --- |
| 交易核心 | Python 3.12、`asyncio`、`pydantic`、`websockets`、Deribit JSON-RPC v2 |
| 持久化 | SQLite（`aiosqlite`）、分桶的净值快照、K 线缓存 |
| REST API | FastAPI + SSE 流式 |
| MCP | Python `mcp` SDK |
| LLM 客户端 | `openai` SDK（任意 OpenAI 兼容端点） |
| 前端 | React 18、TypeScript、Vite、Tailwind、Zustand、Radix UI、ECharts |
| 测试 | `pytest`、`vitest` |

---

## 快速开始

```bash
# 1. 后端
uv sync
export DEEPSEEK_API_KEY=sk-...      # 任何 OpenAI 兼容端点都可
uv run python -m deribit_trading api --env testnet --host 127.0.0.1 --port 8000

# 2. 前端
cd frontend
npm install
npm run dev                          # http://localhost:5173

# 3. 在 Settings → Account Configuration 里填 Deribit 凭据
# 4. 点右下角悬浮按钮打开聊天栏，问一句 "What's the BTC perp price?"
```

首次使用建议先在 Deribit testnet 上跑通。切到生产环境需要在 Settings 里明确二次确认。

---

## 项目哲学

读代码前值得知道的几个设计取舍：

- **原子化数据层，不是 API wrapper。** 每个 MCP 工具是 *最小数据单元*。复杂分析（IV 偏度、期限结构、损益扫描）属于未来 Skill 层的事——由 Skill 层去 *组合* 这些工具，让 agent 表面保持薄、让 LLM 直接对原始数组做推理。
- **Just-in-time 披露。** Tier 1 知识（约 800 tokens）只覆盖 agent *必须知道才能用工具* 的事实。具体的费率表、智能下单内部参数等，由 agent 用 `get_system_status` 之类的工具按需取，而不是预灌进每一轮 prompt。
- **MCP 响应里不嵌"解读"字段。** 工具返回数字；定性判断（"该合约 IV 偏贵"、"期限结构呈 contango"等）由 LLM 或未来的 Skill 模块自己做。
- **不藏式缓存。** 所有工具调用都打 Deribit 实时数据。批量端点（`public/get_book_summary_by_currency`）约 200ms 已经足够快——缓存层的 TTL / invalidate / 一致性复杂度不值得。
- **拒绝预测价格方向，拒绝直给买卖建议。** Agent 给出权衡、损益、风险——不会告诉你 "BTC 会涨"。

---

## 当前状态

- **现在**：完整的交易 UI（下单、撤单、智能下单）+ 专注行情分析、持仓查询、多腿策略建模的 AI 助手。
- **接下来**：为 agent 加入交易类工具（`place_order`、`cancel_order`、`smart_order`），配套下单确认卡流程；Skill 层用于更重的分析（IV 偏度、期限结构、IV-RV）；Tier 2 策略手册。

---

## License

[MIT](./LICENSE) ——随便用，但亏钱了不要找我。这是一个研究工具，不是投资建议。

---

## 致谢

与 [Claude Code](https://claude.com/claude-code) 配对编程完成，包括基于 OpenSpec 的变更规划工作流。
