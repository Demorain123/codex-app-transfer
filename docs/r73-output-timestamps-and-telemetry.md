# r73 — Codex Desktop 每段模型输出时间戳 + 轻量观测

## 目标

r72 的结构化观测没有满足 UI 需求：用户要的是 **Codex Desktop 会话画布里每一个 assistant/model 输出段本身都带可见时间戳角标**，而不是只在 Transfer 日志或版本信息里记录时间。

r73 把该需求放进 Windows No Lagging B 的既有启动钩子：

- 每个可识别的 assistant/model 输出段右上角显示本地 `HH:mm:ss` 小角标。
- 优先读取 Codex 自带的 `data-assistant-message-sent-time` / `time[datetime]`；如果该 build 没暴露原生 sent-time，则使用“该输出段第一次在本机 DOM 中被观察到的时间”。tooltip 会明确标记来源，避免把 fallback 伪装成服务端发送时间。
- MutationObserver 对 React/虚拟列表的 mount/remount 做批处理，避免流式输出时高频全树扫描；重复执行幂等，不在同一输出段叠多个角标。
- A 路径保持原生对照，不注入角标；B 路径才武装该 runtime。
- 不改 prompt、response 文本、session JSONL、app.asar、auth 或 provider 配置。

## 轻量指标

时间戳是 r73 的硬需求；token 指标只是附加能力，不能反过来阻断时间戳。

当 renderer 的 fetch 流里实际可观察到 Codex `token_count` / `last_token_usage` / `model_context_window` 时，r73 才显示右下角轻量 HUD：

- `ctx x%`：`last_token_usage.input_tokens / model_context_window`。
- `out N`：可观察到的 output tokens。
- `tok/s`：当前可观察输出 token 增量 / 本地经过时间。

如果该 Codex Desktop build 走的传输路径没有把这些事件暴露给 renderer，则 HUD 保持隐藏；**不估算、不填 0、不伪造**。后续如果要做稳定的跨重启 token/cost 历史统计，应直接读 `~/.codex/sessions` / `archived_sessions` 的 rollout JSONL，而不是继续扩大 renderer hook。

## 开源项目复用审查

| 项目 | r73 采用的思想 | 许可与处理 |
| --- | --- | --- |
| `KevinKE93/Codex-Monitor` | Codex Desktop 当前 assistant DOM selector、`data-assistant-message-sent-time`、MutationObserver 批处理、虚拟列表幂等注入思路 | MIT；允许参考/改写。r73 为独立实现，保留本文件归因。 |
| `Minghou-Lei/codex-context-used-meter` | 浏览器端动态 DOM 注入、fetch/XHR 观测“有数据才显示”的思路 | MIT；允许参考/改写。 |
| `petergpt/codex-speed-monitor` | 输出 token 增量 / 本地 elapsed time 的 tok/s 思路、流结束后停止刷新 | MIT；允许参考/改写。 |
| `Javis603/token-monitor` | `~/.codex/sessions` + `archived_sessions`、按 session/model/device 聚合的长期方向 | MIT；r73 暂不把大而全 dashboard 重做一遍，只保留后续本地历史页的数据源方向。 |
| `kokotao/codex-token-usage-script` | `token_count`、cache/input/output/context-window 的本地 JSONL 解析方向 | 仓库根目录未找到 LICENSE；**只参考公开行为/数据格式，不复制代码**。 |
| `Tianzora/codex-token-cost` | 按日/model/session/project 聚合与可配置价格的产品思路 | 仓库根目录未找到 LICENSE；**只参考产品思路，不复制代码**。 |

此外调研了 `Kaltorre/codex-usage`、`harveyxiacn/codex-usage-monitor`、`Justin-147/codex-usage-hud`、`CodexBar` 等同类项目。共同结论是：Codex 的稳定 token/context 事实源仍然是本地 rollout JSONL `token_count`，而 Desktop 当前没有一个可供第三方直接挂载的原生常驻 status-bar 插件面。因此 r73 的 UI 角标继续利用已经存在的 No Lagging 启动注入点，但长期统计不应重复造轮子，应复用 JSONL 数据模型。

## 为什么 r73 暂不加入“美元成本”角标

当前 Transfer 面向 Sub2API/Grok/第三方 provider，同一个模型 slug 的实际结算价未必等于 OpenAI 官方 API 价。直接把第三方工具的静态价格表塞进每段回复，会产生看似精确但可能错误的账单数字。因此 r73 先做可验证的时间戳、上下文、输出 token、tok/s；成本功能只有在 provider 能提供明确价格/usage 字段，或用户显式配置价格表后再接入。

## 运行边界

- runtime 只在 No Lagging B 启动时武装；A 不动，便于 A/B。
- Electron main-process startup hook 只负责在 `web-contents-created` / `dom-ready` 时向 window/webview renderer 执行 presentation runtime。
- timestamp runtime 异常必须 best-effort fail-open：不能让 Codex、MCP、subagent 或 Micro/Accessory Guard 因 UI 观测失败而退出。
- 输出角标 selector 依赖 Codex Desktop 当前语义属性；上游 UI 改名后可能需要更新 selector。优先使用语义 data 属性，不依赖 class/hash。

## 本地验收

成功构建后版本必须同时显示：

- 窗口标题：`Sub2API Grok Compat r73 — v2.4.5+73`
- Transfer 顶部角标：`Sub2API Grok Compat r73 · v2.4.5+73`

点击 **No Lagging 启动（B）** 后：

1. 新开一个 Codex task，连续产生多段 assistant/progress 输出。
2. 每个 assistant/model 输出段右上角应各自出现 `HH:mm:ss`，不是整轮只有一个。
3. hover 角标应看到完整本地日期时间，以及 `Codex message time` 或 `first observed locally` 来源。
4. 若 renderer 可观察 `token_count`，右下角才出现 `ctx · tok/s · out` HUD；没有 token 事件时 HUD 不出现也不算时间戳失败。
5. Transfer 的最近一次 B 状态应显示 `outputTelemetry.status=armed` / `runtime=r73.1`。

`build-r73-local.ps1` 在正式 Tauri build 前先对 No Lagging launcher 执行 `node --check`，避免把 JavaScript 语法错误打进本地 release。
