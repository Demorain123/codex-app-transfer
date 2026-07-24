# Sub2API Grok Compat — Windows 使用与验收

本分支在 Codex App Transfer v2.4.5 的原生 Responses passthrough 上，为通过 Sub2API 使用 `grok-*` 模型增加 Codex 私有工具协议兼容；非 Grok 模型保持原生 Responses 直透。

## 推荐拓扑

```text
Codex Desktop
  -> http://127.0.0.1:18080/v1
Codex App Transfer — Sub2API Grok Compat
  -> http://127.0.0.1:8089/v1
Sub2API
  -> Grok / Luna / GPT upstream
```

Sub2API 仍监听 8089，不需要改端口。

## Provider 配置

进入 `提供商 -> 添加提供商 -> 自定义`：

- 名称：`Sub2API`
- Base URL：`http://127.0.0.1:8089/v1`
- API Key：Sub2API 的调用 key
- API 格式：`Responses`
- 鉴权：`Bearer`
- 模型映射：混合 Sub2API provider 推荐全部留空，让请求中的真实 model id 原样交给 Sub2API

当 Provider 为“自定义 + Responses”时会显示 `Sub2API · Grok 兼容`：

- `Grok MCP / Tools 兼容`：推荐开启。只对 `grok` / `grok-*` / `grok/*` 请求生效。
- `Grok Free 缓存兼容`：默认关闭。只有确认 MCP 已工作、但 Sub2API 的 `cache_read_tokens` 在连续轮次仍接近 0 时，再作为 fallback 开启。

保存后将 Sub2API 设为默认 Provider，进入 `路由` 启动 18080 转发，再使用界面的 `重启 Codex App`。

## 为什么模型映射建议留空

Transfer 的 resolver 会先查明确的模型映射，然后回落到 `default`。对一个同时承载 `grok-4.5`、`gpt-5.6-luna`、GPT 等模型的 Sub2API provider，如果把 `default` 填成 `grok-4.5`，未知模型可能被错误改写成 Grok。

全部留空时，未命中的 model 保持原值：

```text
grok-4.5      -> grok-4.5
gpt-5.6-luna  -> gpt-5.6-luna
gpt-5.4       -> gpt-5.4
```

## 首次验收

### 1. 工具 / MCP

新开一个 Grok 4.5 会话，要求模型必须通过 AUQ / `ask_user_questions` MCP 提问。

通过标准：

- `tool_search` 能发现 AUQ；
- Grok 能继续调用发现后的 MCP function；
- Codex 不再出现由于 Sub2API/xAI 422 `ModelInput` 引起的连续 `Reconnecting`。

### 2. 缓存

首次保持 `Grok Free 缓存兼容 = 关闭`。

在同一个 Grok 会话连续交互 2-3 轮，到 Sub2API 用量查看 `cache_read_tokens`（蓝色缓存数字）。

理想情况：第一轮较少/0，第二、第三轮出现明显的 K 级或万级 cache read。

若 MCP 已正常但连续多轮 `cache_read_tokens` 仍接近 0，再开启 `Grok Free 缓存兼容`，新建会话重新测试。该模式会补 `web_search` / `x_search` 作为 cache-route companion，因此可能影响自动工具选择，不建议无条件开启。

### 3. 混合模型回归

同一 Provider 再分别调用 Luna/GPT。确认 Sub2API 实际记录的 model 仍是原 model，并且请求没有经过 Grok tool shim。

## 已知边界

- `image_generation` 等 Grok Responses 不支持的 Codex 私有工具会被丢弃，不属于本兼容层目标。
- 极少见情况下，如果两个 MCP namespace 暴露完全相同的内层 function name，namespace flatten 可能产生名字碰撞；常见 MCP 工具一般使用唯一/带前缀的 function name。
- `Grok Free 缓存兼容` 是显式 fallback，不等于账号 Free 标签检测修复。
- 最终缓存命中取决于 xAI/Sub2API 实际路由，无法仅靠本地单元测试保证。

## 更新与回滚

修改版沿用原应用数据目录和 identifier，便于保留原 Provider/Usage 数据，因此不要同时运行官方版和修改版。

要回滚：关闭 Transfer/Codex，安装官方 Codex App Transfer 即可；Provider 数据仍在原数据目录。官方新版覆盖安装后，本分支的 Grok Compat 代码也会被覆盖。

内置 updater 的默认仓库随构建仓库决定。本分支没有正式 Release 之前，建议不要依赖应用内自动更新来升级 Compat 版；更新上游代码后应重新合并/构建本分支并重新做上述验收。
