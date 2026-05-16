# Deribit Trading Agent

[English](./README.md) · [中文](./README_CN.md)

一个个人用的 **Deribit 衍生品交易终端**，内置一位叫 **Vida** 的 AI 交易助手——可以流式回答关于实时行情、持仓组合、期权策略的问题；在你授权后，还能帮你下单（每一次下单都会弹出确认卡，由你点 Confirm 才会真正成交）。

![Dashboard with AI assistant](assets/screenshots/dashboard.png)

---

## 你能得到什么

一套干净的、单屏的 Deribit 工作台：BTC / ETH 永续、期货、完整期权链——加上右侧一个能 *干活* 而不仅仅是聊天的 AI 助手。

- **多品种实时看板** —— 永续、期货、含希腊值的完整期权链、隐波曲面、净值曲线。
- **智能下单** —— tick 追价 + 意图路由算法，maker 优先成交，可调耐心度。
- **组合 + 风控** —— 持仓、盈亏归因、日亏损限额、保证金率。
- **多账户** —— 一份本地安装管理多个 Deribit 账户。顶栏右上角的 chip 一键切换；每个账户独立的组合、聊天历史、AI 交易开关与审计轨迹。凭据 Fernet 加密本地存储，不会离开你的机器。
- **Vida，你的 AI 交易副驾** —— 流式聊天，配套 13 个行情/账户原子工具、4 个受控的下单工具，每次写操作都有确认卡兜底。

**期权链——波动率微笑 + 期限结构并排显示：**

![Option chain page](assets/screenshots/options.png)

**期货——K 线图、智能下单面板、实时订单簿：**

![Futures page](assets/screenshots/futures.png)

---

## Vida 能为你做什么

Vida 是一个 OpenAI 兼容的 LLM（默认 DeepSeek；同时支持智谱 GLM、OpenAI、vLLM、ollama 等任何 OpenAI-API 兼容端点），背后跑着一套精心设计的工具集 + 流式 ReAct 循环。

**问行情、问账户**——全程只读，所有数字都来自实时工具调用：

- *"BTC 永续现在多少钱？"* → 单合约报价 + 资金费率 + 24h 涨跌。
- *"给我看一下 ETH 期权市场。"* → 一次批量调用拉回整条链，含 IV / 成交量 / 持仓量。
- *"最近的到期日是哪天？IV 微笑长啥样？"* → 到期列表 + 各行权价 IV。
- *"帮我搭一个 27JUN26 的 BTC 70k-80k 看涨价差，要损益和希腊值。"* → 用 `analyze_option_combo` 算多腿损益曲线 + 净希腊值。
- *"今天的 P&L 是被什么拖累的？我离日亏损上限还多远？"* → 持仓、P&L 归因、风控状态。

**让她帮你交易（需开关）** —— 每一次写操作都会弹确认卡：

1. 在 Settings 里为当前账户打开 **AI Trading** 开关，聊天栏标题旁的锁会变成开锁图标。
2. 跟 Vida 说一句类似 *"用限价单买 10 张 BTC-PERPETUAL，价格 58000"*。
3. Vida 回显参数并调用 `place_order`。Agent 循环暂停，UI 渲染一张 **ConfirmationCard**：清晰的下单凭据 + 30 秒倒计时。
4. 点 **Confirm** → 真正提交。点 **Cancel** 或者超时 → 工具返回错误，Vida 自动调整计划。

Vida 可以调用的写工具：
- `place_order`、`cancel_order`、`smart_order`、`cancel_smart_order` —— 每一次都被确认卡拦截。
- 每次成功或被拒的写调用都会写入本地审计日志。

她 **拒绝预测价格方向**，也 **拒绝直给买卖建议** —— 只给出权衡、损益、希腊值，以及什么样的情况会让一个策略失效。

---

## 快速开始

### 1. 注册 Deribit 账户

如果你还没有账户，请用我的邀请链接注册：

👉 **[https://www.deribit.com/?reg=20899.657](https://www.deribit.com/?reg=20899.657)**

然后创建 API key：

1. 登录后进入 **Account → API**。
2. 点 **Add new key**，填一个标签（比如 `vida-local`），勾上需要的权限：`trade:read_write`、`account:read`、`wallet:read`。
3. 复制 **Client ID** 和 **Client Secret** —— 第 4 步要用。
4. **强烈建议先在 testnet 玩一遍。** 同样的注册链接，但登录地址换成 [test.deribit.com](https://test.deribit.com/)，单独生成一个 testnet 的 API key。App 默认就是 testnet，需要在 Settings 里明确二次确认才会切到生产环境。

### 2. 起后端

```bash
git clone https://github.com/ipatpat/deribit-trading.git
cd deribit-trading
uv sync
export DEEPSEEK_API_KEY=sk-...      # 或 OPENAI_API_KEY / ZHIPU_API_KEY 等
uv run python -m deribit_trading api --env testnet --host 127.0.0.1 --port 8000
```

### 3. 起前端

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

### 4. 添加你的 Deribit 账户

1. 打开 `http://localhost:5173`，首次启动会引导你添加账户。
2. **Settings → Account Configuration → Add Account**：粘贴第 1 步的 Client ID + Client Secret，选 `testnet`，保存。
3. 连接成功后，顶栏右上角的 chip 会自动切到新账户。

### 5. 跟 Vida 聊聊

1. 点右下角的悬浮按钮打开聊天栏。
2. 试一下推荐 prompt，或者直接问 *"BTC 永续现在多少钱？"*。
3. 想让她下单：**Settings → AI Trading → On**，然后让她在 testnet 上下一个小单。点确认卡的 Confirm 才会真正提交。

---

## 技术栈

| 层 | 技术 |
| --- | --- |
| 交易核心 | Python 3.12、`asyncio`、`pydantic`、`websockets`、Deribit JSON-RPC v2 |
| 持久化 | SQLite（`aiosqlite`）、分桶净值快照、K 线缓存、写调用审计日志 |
| REST API | FastAPI + SSE 流式 |
| MCP | Python `mcp` SDK（13 个原子数据工具 + 4 个受控写工具） |
| LLM 客户端 | `openai` SDK（任意 OpenAI 兼容端点） |
| 前端 | React 18、TypeScript、Vite、Tailwind、Zustand、Radix UI、ECharts |
| 测试 | `pytest`、`vitest` |

---

## 设计取舍（给好奇的人）

读代码前值得知道的几个设计取舍：

- **原子化数据层，不是 API wrapper。** 每个 MCP 工具是 *最小数据单元*。复杂分析（IV 偏度、期限结构、损益扫描）属于未来 Skill 层——由 Skill 层去 *组合* 这些工具，让 agent 表面保持薄、让 LLM 直接对原始数组做推理。
- **Just-in-time 披露。** Tier 1 知识（约 800 tokens）只覆盖 agent *必须知道才能用工具* 的事实。费率表、智能下单内部参数等按需取，不预灌进每一轮 prompt。
- **MCP 响应里不嵌"解读"字段。** 工具返回数字；定性判断（"该合约 IV 偏贵"、"期限结构呈 contango"等）由 LLM 自己做。
- **不藏式缓存。** 所有工具调用都打 Deribit 实时数据。批量端点约 200ms 已经够快——缓存层的复杂度不值得。
- **确认卡优于自主交易。** Vida 可以调用写工具，但每一次调用都被一张 30 秒倒计时的确认卡拦截。没有批量授权、没有"记住我的选择"、没有自动驾驶。
- **拒绝预测价格方向，拒绝直给买卖建议。** Agent 给出权衡、损益、风险——不会告诉你 "BTC 会涨"。

---

## License

[MIT](./LICENSE) ——随便用，但亏钱了不要找我。这是一个研究工具，不是投资建议。

---

## 致谢

与 [Claude Code](https://claude.com/claude-code) 配对编程完成，包括基于 OpenSpec 的变更规划工作流。
