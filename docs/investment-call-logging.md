# Investment Agent 调用链日志

应用把关键方法的进入、退出和失败写成 JSON，输出到三个服务现有的 CloudWatch 日志组。
不需要新建 AWS 角色、日志服务或数据库表。默认级别为 `INFO`；正常健康检查不产生日志。
通用字符串处理、属性读取和第三方库内部函数不逐行记录。

## 在 CloudWatch 查看一次提问

区域选择 **Asia Pacific (Singapore) / ap-southeast-1**，进入 **Logs Insights / Log Analytics**，同时选择：

- `/ecs/ai-financial-wellness-coach/frontend`
- `/ecs/ai-financial-wellness-coach/backend`
- `/ecs/ai-financial-wellness-coach/ai`

先选对时间范围，找到最近的回答：

```text
fields @timestamp, service, event, correlation_id, journey_id, trace_id, selected_agents, blocked
| filter event = "coach.response.ready"
| sort @timestamp desc
| limit 20
```

复制其中一个 `correlation_id`，查看整个请求经过的方法：

```text
fields @timestamp, service, event, event_type, method, caller_method, span_id, parent_span_id,
       duration_ms, status_code, agent, component, response_type, selected_agents, blocked, details
| filter correlation_id = "替换为请求编号"
| sort @timestamp asc
| limit 10000
```

`caller_method → method` 表示**被记录的应用调用边界**，中间可能经过未展开的框架调度。
同一方法每执行一次都会产生新的 `span_id`；用 `parent_span_id` 找到调用它的那次执行。
并行 Agent 的时间会交错，因此不要仅凭日志行的先后顺序判断父子关系。
`method.completed` 只表示方法正常返回；是否 HTTP 成功、安全拦截或内容合格，要分别看
`status_code`、`blocked` 和质量评审结果。

## 登录到回答展示

| 阶段 | 主要方法与记录 | 能看到的内容 |
| --- | --- | --- |
| 点击登录 | `ui.auth.require_authenticated_user` → `streamlit.user_info.login` | `auth.login_requested` |
| 登录后回到应用 | `ui.auth.require_authenticated_user` | `auth.session_authenticated`，生成会话 `journey_id` |
| 后端验签与归属检查 | `require_principal` → `OidcTokenVerifier.verify` → `enforce_user_access` | 认证类型、接受或拒绝、方法失败类型 |
| 提交聊天 | `ui.pages.coach_page` → `client.build_request` → `BackendClient.ask_coach` → `BackendClient._request` | 请求编号、脱敏路由、问题长度 |
| 后端准备请求 | `app.api.routes.coach` → `SQLAlchemyUserRepository.get_financial_snapshot` | 是否取得持久化快照，不记录金额或账户资料 |
| 调用 AI 服务 | `AIServiceClient.coach` → AI 中间件 → `app.main.coach` | 同一请求编号、跨服务父调用编号、HTTP 状态 |
| 调度工作流 | `AgentOrchestrator.handle` → `_guard_input` → `_route` → `_run_ready_tasks` → `_execute_task` | 安全检查、选中的 Agent、任务编号、并行、依赖和重试 |
| 投资教育 | `BaseAgent.run_task` → `InvestmentEducationAgent._ground` → `build_education_context` | 教育证据是否足够、结果数量、语种 |
| 检索 | `RequestScopedEducationRetriever.retrieve` → `BedrockEducationRetriever.retrieve` → `_retrieve` | 缓存命中、知识库与版本、检索/接受/拒绝数量 |
| 模型响应 | `generate_structured_response` → `TracingModelGateway.generate` → `BedrockModelGateway.generate` → `parse_structured_response` | 模型、调用组件、输入/输出长度、token 数、响应类型、校验和纠正重试 |
| 汇总 | `AgentOrchestrator._synthesize` | `synthesis.strategy` 区分直接使用教育 Agent 答案、澄清问题、模型汇总 |
| 独立合规检查 | `_review_compliance` → `RiskComplianceAgent.validate` → Policy RAG/模型 | 独立政策证据、允许或拦截 |
| AI 封装 | `_finalize` → AI `coach.response.ready` | `CoachResponse` 字段名、来源数、最终状态与答案长度 |
| 后端封装与保存 | `AIServiceClient.coach` → `CoachResponse.model_validate` → 聊天/审计仓库 → `Session.commit` | 验证、安全过滤、保存是否完成、最终响应结构 |
| 读取已保存回答 | `get_chat_session` → `SQLAlchemyChatRepository.get` → `_chat_session_response` → `_message_explanation` | 聊天记录与解释字段封装、历史内容安全过滤 |
| 前端展示 | `BackendClient._request` → `ui.pages._render_coach_message` → `_render_coach_explanation` | 响应接收、JSON 解包、匹配答案的 `coach.response_rendered` 事件 |

图中的模型与检索调用可能因安全拦截、资料不足、缓存命中或直接使用专业 Agent 答案而跳过。
跳过是实际执行路径的一部分，不应把它当成日志缺失。

## 四种编号

- `journey_id`：应用观察到登录成功后，为该 Streamlit 会话随机生成；串联该会话的后续请求。
- `correlation_id`：一次应用操作/请求的编号，随 HTTP 请求从前端传到后端、AI；响应头也返回。
- `span_id` / `parent_span_id`：一次方法调用及其父调用。
- `trace_id`：AI 每次工作流独立生成的编号，连接响应审计与工作流事件。它不由公开客户端编号决定；后端在调用 AI 前生成，并通过私有 `X-Workflow-ID` 传递。

登录跳转由 Cognito 与 Streamlit 实现。跳转前后的 Streamlit 会话可能重建，因此
`auth.login_requested` 与登录后的 `journey_id` 不保证一一关联；日志不会假装看到了
Cognito 内部密码验证、MFA 或 token 交换的完整方法栈。后端 JWT 验签是独立的可观测检查。
应用重开、登出或身份切换会结束原来的会话关联。追踪头只用于排查问题，绝不参与认证或授权。

要从登录后开始查看整个会话，把上面查询的过滤条件换成：

```text
| filter journey_id = "替换为会话编号"
```

## 明确标记的合成测试：查看完整问答

默认日志不记录提问、模型原文、最终答案、财务快照、身份声明、密码或令牌。
经项目负责人授权，**仅后端**可以额外记录 `coach.synthetic.exchange`，并且以下条件必须全部满足：

1. 后端已经验证独立的自动化 API key；普通 OIDC 登录用户不满足此条件。
2. `user_id` 使用部署配置允许的合成测试前缀，例如 `deployment-`。
3. `APP_ENV` 为 `local`、`test` 或 `demo`；其他环境不记录原文。
4. 该次 `/api/coach` 请求明确带 `X-Synthetic-Log: true`。
5. 后端已完成最终答案的安全校验，并成功提交聊天记录。

此事件只有该测试问题和**安全过滤后的最终答案**，不会把系统提示词、未经校验的模型草稿、
财务快照或完整 `audit` 对象复制进日志。前缀和测试标记不能证明输入是合成资料，测试人员仍须
使用合成问题和合成档案。不得把真实用户资料放入这个测试通道。

```text
fields @timestamp, correlation_id, journey_id, question, answer
| filter event = "coach.synthetic.exchange"
| sort @timestamp desc
| limit 50
```

Python 合成测试客户端可显式设置 `BackendClient(automation_api_key=测试密钥, synthetic_log=True)`；
密钥从受控环境读取，不要放进代码、命令参数、截图或日志。普通产品页面没有原文日志开关。
未带标记的自动化请求、普通用户伪造标记、失败调用和被拒绝的请求都不会产生原文问答事件。
安全拦截若正常返回并成功保存，会记录安全拒绝答案，不记录被拦截的模型草稿。

## 错误与开销

```text
fields @timestamp, service, correlation_id, method, caller_method, exception_type, error_code, status_code
| filter event = "method.failed" or event = "request_failed" or event_type = "workflow.failed"
| sort @timestamp desc
| limit 100
```

错误只记录类型和受限代码，不记录异常原文。每个关键方法通常产生两条日志，加上阶段事件；
并行与重试会增加条数。CloudWatch 仍使用现有日志组保留期；日志权限同样可以访问合成问答原文。
不启用全局 HTTP/SDK DEBUG，也不抓取密码、cookie、Authorization 头或 Cognito 回调参数。
容器关闭重复的 Uvicorn 原始访问日志，应用改用不含用户路径参数的路由模板记录访问。

这些日志用于理解程序执行和排查故障，不是模型隐藏推理，也不证明金融答案已达到 99% 质量。


## 持久化决策记录

后端现在在 AI 执行前创建运行记录，并逐条提交过滤后的决策事件。失败、超时或没有最终回答的请求也可以查询运行状态。详见 [Durable decision traces](durable-decision-traces.md)，包括升级顺序、查询方式、权限、保留期与故障边界。
