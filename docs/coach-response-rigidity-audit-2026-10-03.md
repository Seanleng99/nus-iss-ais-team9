# Coach response rigidity audit

Date: 3 October 2026 (Asia/Singapore)

The strongest evidence points to application behavior around the model: premature local replies, lost context, forced routing, missing data, restrictive specialist preflight, and replacement of generated answers. Model configuration is a contributing design constraint, but changing the model or increasing temperature will leave the reproduced failures intact.

## Scope and evidence

Inventoried the repository and scanned all 305 authored Python files under `apps`, `infra`, and `scripts` (65,151 lines) with an AST/text pass. Traced the Coach request through frontend, backend, AI orchestration, specialist agents, tools, retrieval, compliance, persistence, and rendering. Reviewed shared language data, current and older prompt sets, deployment configuration, evaluation workflows, related tests, and design documentation. Generated dependencies, caches, binary documents/diagrams, credentials, and live infrastructure were outside this code audit.

The static scan found 2,517 `if` nodes, 154 `re.compile` calls, 99 `.split()` calls, 192 `.join()` calls, and 192 `.strip()` calls across Python source and tests. These counts describe the scan, not defects: the findings below identify where text processing changes meaning or bypasses reasoning.

Evidence labels:

- **Reproduced:** exercised locally with pure-function probes, scripted model responses, or in-memory SQLite and a mocked AI service. No live records were changed.
- **Code-confirmed:** verified against the active data flow, without claiming an observed live model response.
- **Configuration-dependent:** applies to the checked-in launch/configuration path; the running deployment was not inspected.

Priorities: **P1** materially wrong answers, lost context, or action integrity; **P2** substantial conversational/design gaps; **P3** narrower edge cases or presentation friction. These are audit priorities, not measured production incident rates.

No application code was modified. Only this report was added.

## Findings

### A01 — P1: broad budget-status matching answers the wrong question before AI

**Reproduced.** `on track` and `how am I doing` are authoritative budget-status triggers, without requiring a budget subject. The backend returns before `ai_service.coach`.

“Am I on track to reach my emergency fund goal?” returned the canned instruction to add monthly income on Profile plus recorded spending of SGD 0.00, with no AI call. Adding a word such as “review” changes routing because another regex excludes it. The question is about goal feasibility, but the selected response is a spending-status template.

Evidence: [budget_alert.py:19](C:/ai-financial-wellness-coach/apps/backend/app/services/budget_alert.py:19), [routes.py:185](C:/ai-financial-wellness-coach/apps/backend/app/api/routes.py:185).

Change direction: require explicit or context-resolved budget intent. Deterministic computation can remain authoritative; phrase occurrence should not determine the conversational subject.

### A02 — P2: deterministic rules override semantic routing and continue unrelated drafts

**Reproduced with a scripted semantic router.** A pending goal always forces goal capture; a pending budget always forces budget capture. Words including `bill`, `payday`, and `cash flow` force budget capture even in explanatory questions. This contradicts the runtime router instruction that unrelated questions do not continue drafts.

When the scripted router chose education only with all capture flags false, “Explain bonds” still added goal/budget capture if a corresponding draft existed. “What is cash flow?” and “What does a bill mean?” forced budget capture. Extractors may subsequently reject an unrelated operation, so this proves extra work and context contamination, not an unauthorized save.

Evidence: [orchestrator.py:553](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:553), [orchestrator.py:564](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:564), [orchestrator.py:568](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:568).

Change direction: constrain authorization and ownership deterministically; resolve whether the current turn continues a draft semantically. Keep an unrelated draft available without making it the active task.

### A03 — P1: missing-record preflight prevents general coaching and hypothetical calculations

**Reproduced on normal specialist paths.** Missing-input questions are returned before the writer runs. Budget requires income; Goal Strategy generally requires saved goals and income. Session facts are explicitly prohibited as calculation inputs.

- “Explain how budgeting works” with no profile income asked for monthly income.
- “How can I prioritize several savings goals?” asked for target amounts/dates.
- “If I want $1200 in 12 months, how much would I save monthly?” with correctly attributed user-reported target/duration asked the user to create a saved goal.

Draft extraction and some education/emergency-fund routes can bypass these checks; the defect is the intent-insensitive preflight on the normal narrative path.

Evidence: [base.py:354](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/base.py:354), [budget.py:146](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/budget.py:146), [goal_strategy.py:112](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/goal_strategy.py:112), [base.py:113](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/base.py:113).

Change direction: distinguish explanation, hypothetical calculation, analysis of saved records, and proposed mutation. Permit labeled hypothetical calculations from validated user-provided inputs without treating them as saved facts.

### A04 — P2: follow-up comprehension depends on Markdown formatting

**Reproduced.** “Explain the second option” resolves when the previous answer uses contiguous numbered lines, but returns `ambiguous/MISSING_ORDERED_OPTIONS` after equivalent bullets or a table. The deterministic result overrides the semantic router and stops the writer before it can interpret the dialogue.

Evidence: [follow_up.py:223](C:/ai-financial-wellness-coach/apps/ai-service/app/core/follow_up.py:223), [orchestrator.py:602](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:602), [base.py:70](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/base.py:70).

Change direction: persist referenceable subjects/options as structured conversational metadata, with a bounded semantic resolution fallback. The user's meaning should survive changing bullets into a table.

### A05 — P1: validated local replies disappear from the next turn's context

**Reproduced.** Backend-produced replies normally lack an orchestration trace. The history loader treats every assistant message without a trace as unavailable; older-summary generation excludes it too.

After “How am I doing?” followed by “Please explain that status”, the model received “The previous answer is unavailable or was withheld. Ask for clarification.” instead of the actual status. Confirmations, recalls, forecasts and transaction edits have the same provenance problem.

Evidence: [routes.py:336](C:/ai-financial-wellness-coach/apps/backend/app/api/routes.py:336), [repositories.py:944](C:/ai-financial-wellness-coach/apps/backend/app/infrastructure/repositories.py:944), [conversation_summary.py:64](C:/ai-financial-wellness-coach/apps/backend/app/services/conversation_summary.py:64).

Change direction: persist explicit provenance for validated deterministic replies. A response without model evidence is different from a withheld response.

### A06 — P2: memory relies on exact grammar and stores only short leading excerpts

**Reproduced fact-extraction gaps; code-confirmed truncation.** “My income is 5000.” creates a session fact. “I bring home around 5k each month”, “I earn 5000 and my monthly expenses are 2000”, and the comma-separated equivalent create none. Clause splitting and full matches lose ordinary paraphrases and compound statements.

Recent context contains eight messages, each cut at 1,500 characters. Older memory keeps six notes with the first 240 user characters and 160 assistant characters, reserving at most two preference/objective slots. Later options, decisions, qualifications and preferences can disappear while remaining visible to the user. Pending fields are also inferred by scanning assistant question prose.

Evidence: [session_context.py:112](C:/ai-financial-wellness-coach/apps/backend/app/services/session_context.py:112), [session_context.py:230](C:/ai-financial-wellness-coach/apps/backend/app/services/session_context.py:230), [repositories.py:938](C:/ai-financial-wellness-coach/apps/backend/app/infrastructure/repositories.py:938), [conversation_summary.py:94](C:/ai-financial-wellness-coach/apps/backend/app/services/conversation_summary.py:94).

Change direction: extract attributed, uncertainty-aware facts into typed fields; carry pending-field IDs directly. Use a token budget and structured decisions/preferences/options, and retrieve older turns when referenced.

### A07 — P1: saved personalization settings are dropped before model execution

**Reproduced by task construction.** The UI collects literacy/accessibility preferences, and the backend snapshot includes income frequency/stability, household size, dependants, housing status and those preferences. Router, specialist tasks and synthesis omit them. Task role allowlists exclude preferences.

A snapshot marked beginner, shorter/plain-language responses, weekly income and variable stability produced tasks containing none of those fields for any specialist. Changing these saved settings cannot influence normal Coach wording or reasoning through the profile path; a user must restate them in retained dialogue.

Evidence: [pages.py:1409](C:/ai-financial-wellness-coach/apps/frontend/ui/pages.py:1409), [repositories.py:508](C:/ai-financial-wellness-coach/apps/backend/app/infrastructure/repositories.py:508), [orchestrator.py:442](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:442), [orchestrator.py:1770](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:1770), [schemas.py:244](C:/ai-financial-wellness-coach/apps/ai-service/app/core/schemas.py:244).

Change direction: pass a minimal allowed coaching-preferences object to relevant writers and financial-context fields to appropriate tools. Make saved settings have an observable effect.

### A08 — P1: spending analysis loses supplied history and the selected period

**Reproduced.** The Spending task copies only `recent_transactions`, and its schema permits only that field. The specialist expects `historical_transactions` and `period_start`, so supplied history/period never reach it.

With August SGD 100, September SGD 300 and a September analysis period, the specialist received only the September transaction and reported one month of data with no comparison trend. The default date then comes from the execution clock.

Separately, the backend snapshot labels up to 500 records across all dates as `recent_transactions`, with no period or completeness metadata; recurring expenses are taken from the same bounded list. This can mix periods and silently omit data.

Evidence: [orchestrator.py:1772](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:1772), [schemas.py:245](C:/ai-financial-wellness-coach/apps/ai-service/app/core/schemas.py:245), [spending.py:61](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/spending.py:61), [repositories.py:489](C:/ai-financial-wellness-coach/apps/backend/app/infrastructure/repositories.py:489), [repositories.py:629](C:/ai-financial-wellness-coach/apps/backend/app/infrastructure/repositories.py:629).

Change direction: provide an explicit analysis period, historical window, as-of date and completeness indicators; query the appropriate owned data rather than relying on an implicitly bounded list.

### A09 — P1: monthly comparison date arithmetic is wrong in both analyzers

**Reproduced.** For 1 October, `current_month_start - timedelta(days=current_month_start.day)` produces 30 September, so the previous-month interval is only 30 September. Current-month filtering has no upper boundary, so November records also enter October totals.

| Input transaction | Food expense |
|---|---:|
| 15 September | SGD 100 |
| 30 September | SGD 10 |
| 2 October | SGD 100 |
| 1 November | SGD 50 |

October analysis returned current SGD 150, previous SGD 10, **+1,400%**. Complete calendar-month October versus September is SGD 100 versus SGD 110, about **−9.1%**. The same bug exists in backend and AI-service copies.

Evidence: [AI spending_analyzer.py:324](C:/ai-financial-wellness-coach/apps/ai-service/app/tools/spending_analyzer.py:324), [backend spending_analyzer.py:310](C:/ai-financial-wellness-coach/apps/backend/app/services/spending_analyzer.py:310).

Change direction: use explicit calendar boundaries and distinguish month-to-date from completed-month comparisons. Share the calculation implementation.

### A10 — P2: hardcoded statistical confidence overstates sparse data

**Reproduced.** Six transactions spread across six months are rated `excellent`. One Saturday transaction produces a weekend-concentration pattern with confidence **0.85**. Quality counts months containing any data, without measuring coverage, sample size or continuity; the writer interprets `excellent` as comprehensive and reliable.

Trend thresholds, the 29% weekend baseline, and fixed 0.85/0.75 confidence scores are heuristics rather than validated personal or population estimates. They are delivered as facts to the writer.

Evidence: [spending_analyzer.py:128](C:/ai-financial-wellness-coach/apps/ai-service/app/tools/spending_analyzer.py:128), [spending_analyzer.py:260](C:/ai-financial-wellness-coach/apps/ai-service/app/tools/spending_analyzer.py:260), [spending.py:133](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/spending.py:133).

Change direction: distinguish descriptive totals from supported patterns; require sample/coverage criteria and label heuristic flags. Avoid converting fixed constants into apparent statistical certainty.

### A11 — P1: week/year lookups fetch only one month

**Reproduced with in-memory records.** The query handler calls `list_records(period_start=start)` for week/year requests, but the repository bounds that call to `start` through `next_month(start)`.

January SGD 10, September SGD 20 and October SGD 30 yielded “this year” = SGD 10. A week spanning 28 September–4 October yielded SGD 20 instead of SGD 50. Filtering the returned rows afterward cannot restore excluded records.

Evidence: [transaction_staging.py:115](C:/ai-financial-wellness-coach/apps/backend/app/services/transaction_staging.py:115), [repositories.py:621](C:/ai-financial-wellness-coach/apps/backend/app/infrastructure/repositories.py:621).

Change direction: query explicit start/end boundaries and aggregate complete results in storage. The repository already has a date-range method.

### A12 — P1: transaction lookups ignore requested filters and narrow queries to day/period templates

**Reproduced.** “Show only my food expenses this month” included an October taxi under Transport. The query contract carries a date but no category/merchant/amount/range/aggregation fields. The final handler filters by date and expense type only, then builds a fixed comma-joined list.

Period matching supports a small `this|last` × `month|week|year` grammar. Unresolved broad questions can become “Which day should I look up?” even when the requested analysis is not a single-day lookup.

Evidence: [spending_capture.py:71](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/spending_capture.py:71), [transaction_staging.py:71](C:/ai-financial-wellness-coach/apps/backend/app/services/transaction_staging.py:71), [transaction_staging.py:104](C:/ai-financial-wellness-coach/apps/backend/app/services/transaction_staging.py:104).

Change direction: extract a typed owned-data query with filters, date boundaries and requested output/analysis. Ask only for genuinely unresolved fields.

### A13 — P1: recurring forecasts can count income as expense and annual amounts as monthly

**Reproduced.** The local forecast reads all transaction types, checks only `recurring`, and labels their sum “per month”. A recurring SGD 5,000 salary and SGD 1,200 annual insurance yielded estimated upcoming spending of **SGD 6,200 per month**.

Prefix-token deduplication can also merge `Netflix` and `Netflix premium for family` without a stable obligation identity.

Evidence: [recurring_forecast.py:54](C:/ai-financial-wellness-coach/apps/backend/app/services/recurring_forecast.py:54), [recurring_forecast.py:60](C:/ai-financial-wellness-coach/apps/backend/app/services/recurring_forecast.py:60), [recurring_forecast.py:86](C:/ai-financial-wellness-coach/apps/backend/app/services/recurring_forecast.py:86), [recurring_forecast.py:113](C:/ai-financial-wellness-coach/apps/backend/app/services/recurring_forecast.py:113).

Change direction: use expense-only obligations with cadence, due dates and stable identities. Clarify ambiguous cadence/duplicates instead of assuming monthly recurrence or silently merging names.

### A14 — P1: pending edit/delete state crosses chats

**Reproduced only in an isolated in-memory database.** Pending edits/deletions are keyed by `user_id`, not `(user_id, session_id)`. “Delete October taxi” in chat A followed by “yes” in fresh chat B deleted the record without AI. The last-saved pointer is similarly user-scoped. Both stores are process-local, adding restart/multiple-worker inconsistency.

This is an action-integrity defect beyond response style: confirmation is detached from the conversation that displayed the proposal.

Evidence: [transaction_capture.py:405](C:/ai-financial-wellness-coach/apps/backend/app/services/transaction_capture.py:405), [transaction_capture.py:452](C:/ai-financial-wellness-coach/apps/backend/app/services/transaction_capture.py:452), [transaction_capture.py:1220](C:/ai-financial-wellness-coach/apps/backend/app/services/transaction_capture.py:1220).

Change direction: persist pending actions and last-saved pointers per chat and bind confirmation to an exact proposal/revision.

### A15 — P1/P2: backend staging replaces the final model answer and can lose the selected language

**Code-confirmed answer replacement; reproduced language mismatch.** After AI generation/compliance, staging handlers replace `response.answer` with goal, budget or spending templates. This discards tone, requested format, explanatory context and answers to additional intents whenever a supported draft/query is present.

A `zh-Hans` request returned “Saved: Lunch for SGD 5.00 on 2 Oct 2026 under Food.” while its audit still reported `zh-Hans`. Localization on the separate local-return path does not cover these post-AI replacements.

Evidence: [routes.py:245](C:/ai-financial-wellness-coach/apps/backend/app/api/routes.py:245), [transaction_staging.py:397](C:/ai-financial-wellness-coach/apps/backend/app/services/transaction_staging.py:397), [goal_capture.py:178](C:/ai-financial-wellness-coach/apps/backend/app/services/goal_capture.py:178), [budget_capture.py:253](C:/ai-financial-wellness-coach/apps/backend/app/services/budget_capture.py:253).

Change direction: return structured validated action/query outcomes, then compose and localize the user-facing reply once. Keep write confirmation and verified amounts authoritative.

### A16 — P2: Spending forces the same coaching essay for different questions

**Code-confirmed prompt pressure.** The runtime message mandates five sections, 2–3 findings, 2–3 actions, encouragement and 2–3 follow-up questions. A narrow question still receives this instruction. The prompt includes unsourced “Many people spend 10–15% on dining” and a fixed monetary example, competing with the system instruction to answer the user's specific question.

The synthesis payload carries summaries/rationales, not full conversation or calculation data, and forbids new explanations/examples. Some paths concatenate clarification templates or directly reuse specialist prose, so the last stage cannot reliably repair an unsuitable response structure.

Evidence: [spending.py:171](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/spending.py:171), [spending.py:182](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/spending.py:182), [orchestrator.py:1382](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:1382), [orchestrator.py:1429](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:1429).

Change direction: choose response depth from the request and preferences. Remove unsourced population benchmarks. Allow a final composer to adapt wording while preserving verified facts and evidence boundaries.

### A17 — P2: spending prompts contradict the actual save/confirmation contract

**Code-confirmed.** The v6 Spending prompt tells the model that spending statements are saved automatically; actual capture returns an unsaved draft requiring backend preview/confirmation. v7 retains the automatic-save language.

Evidence: [v6/prompts.json:4](C:/ai-financial-wellness-coach/apps/ai-service/prompts/v6/prompts.json:4), [spending.py:33](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/spending.py:33).

Change direction: describe exactly which actions are proposed, confirmed and saved. Generate user-facing state from backend outcomes, not contradictory prompt prose.

### A18 — P2: ordinary language preferences are intentionally ignored

**Reproduced.** The shared locale resolver accepts message/history but does not inspect them. The frontend defaults to English and always submits its workspace selector. “Please answer in Chinese” remains English when English is selected; the inverse happens in Chinese mode. Writer/synthesis prompts explicitly override conversational language requests.

Profile options include Malay and Tamil, but supported response locales are only English and Simplified Chinese. Unsupported saved preferences fall back; the UI does disclose the workspace-language rule. Existing tests explicitly protect the language lock, so this is a product-policy gap rather than an accidental model failure.

Evidence: [coach_i18n/__init__.py:42](C:/ai-financial-wellness-coach/apps/shared/coach_i18n/__init__.py:42), [coach_language.py:14](C:/ai-financial-wellness-coach/apps/frontend/ui/coach_language.py:14), [pages.py:1266](C:/ai-financial-wellness-coach/apps/frontend/ui/pages.py:1266), [base.py:249](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/base.py:249), [test_coach_language.py:164](C:/ai-financial-wellness-coach/apps/frontend/tests/test_coach_language.py:164).

Change direction: make explicit current-turn language requests a supported preference, synchronize the selector, and clearly scope unsupported languages.

### A19 — P1: harmless words are classified as prompt injection

**Reproduced.** A regex blocks every occurrence of `password`, `secret`, or `api key`, regardless of purpose. All three requests below failed before model reasoning:

- “What is the secret to saving money?”
- “How can I avoid password scams?”
- “Explain why I should never share my password.”

The same inspection is applied to generated prose, so an otherwise helpful fraud-prevention explanation can also be withheld.

Evidence: [guardrails.py:22](C:/ai-financial-wellness-coach/apps/ai-service/app/core/guardrails.py:22), [guardrails.py:94](C:/ai-financial-wellness-coach/apps/ai-service/app/core/guardrails.py:94), [risk_compliance.py:554](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/risk_compliance.py:554).

Change direction: distinguish credential disclosure/exfiltration or instruction override from ordinary metaphors, quotations and security education. Preserve strict controls for actual prohibited actions.

### A20 — P1/P2: privacy/allocation regexes overblock household budgeting and savings guidance

**Reproduced matching; code-confirmed hard-block path.** “My wife's income is $3000. Help us budget.” produces `data_access:third_party_request`; “My wife earns $3000...” does not. A possessive financial noun is treated as an attempt to retrieve private records, even when the user supplies the amount.

“You should put your monthly savings into an emergency fund.” matches `regulated_advice:personalized_allocation`, despite containing no investment-product allocation. That category is not one of the ambiguous findings eligible for contextual language review.

Evidence: [risk_compliance.py:154](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/risk_compliance.py:154), [risk_compliance.py:78](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/risk_compliance.py:78), [risk_compliance.py:211](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/risk_compliance.py:211), [risk_compliance.py:579](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/risk_compliance.py:579).

Change direction: require actual data-access intent for cross-user blocking; distinguish ordinary savings/budget coaching from personal investment-product instructions.

### A21 — P3: redaction and fallback category substrings erase legitimate meaning

**Reproduced.** “I spent SGD 68901234 on property” becomes “I spent SGD [REDACTED_PHONE] on property.” The phone-shaped number is a financial amount in context. Numeric snapshot facts have an exception elsewhere, but user text does not.

Fallback category matching labels `baggage fee` as shopping (`bag`) and `business insurance` as transport (`bus`). This fallback is used when extraction supplies no category, so it does not affect every transaction.

Evidence: [guardrails.py:13](C:/ai-financial-wellness-coach/apps/ai-service/app/core/guardrails.py:13), [transaction_capture.py:523](C:/ai-financial-wellness-coach/apps/backend/app/services/transaction_capture.py:523).

Change direction: distinguish typed monetary values from identifiers before redaction; use word boundaries or a validated category classifier with uncertainty.

### A22 — P2: education retrieval compresses meaning into canonical topics and lexical overlap

**Reproduced at helper/retrieval level; end-to-end outcome depends on router hints.** `education_topics` recognizes “diversification” and “compound interest” but not “putting all my eggs in one basket”, “earning interest on earlier interest”, `IPO`, or `investment volatility`. Some of those concepts exist in the packaged documents.

The semantic router does explicitly recognize paraphrases and may supply a canonical topic or `general investment concepts`; this is an existing mitigation and means the helper miss is not proof of universal end-to-end failure. However, deterministic follow-up routing can overwrite those semantic hints (A04), and a no-topic result produces an evidence-gap reply before the education writer.

Deployed retrieval is a lexical baseline using ASCII word tokens, stemming and a small synonym list. “What is the difference between an accumulating and a distributing ETF?” becomes an ETF-only retrieval query; “What are the current fixed deposit rates?” becomes fixed-deposit-only. Specific distinctions/time intent are absent from search. Raw Chinese produces no lexical tokens; current canonical English queries compensate for this, so Chinese tokenization is a constraint rather than a demonstrated failure of every Chinese request.

Evidence: [education_access.py:108](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/education_access.py:108), [education_access.py:242](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/education_access.py:242), [orchestrator.py:494](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:494), [ranking.py:39](C:/ai-financial-wellness-coach/apps/ai-service/app/rag/ranking.py:39), [local_documents.py:104](C:/ai-financial-wellness-coach/apps/ai-service/app/rag/local_documents.py:104).

Change direction: preserve sanitized semantic distinctions and question intent in retrieval queries; evaluate retrieval on paraphrases and subtopic comparisons. Keep personal identifiers out of queries and maintain source governance.

### A23 — P2: fixed retrieval/chunk budgets can discard useful evidence

**Code-confirmed.** Local chunks flatten paragraph whitespace, attach heuristic headings and form overlapping windows up to 360 words. Retrieval defaults to three hits and limits two hits per source. Multi-topic retrieval queries only the first six topics, keeps at most nine candidates, then admits whole chunks until 1,200 words; chunks that exceed the remaining budget are skipped rather than trimmed or balanced by unresolved subject.

Fine-grained coverage checking is limited to a fixed topic subset and detects terms in passages rather than validating whether the passage answers the requested distinction. Thus “grounded” primarily describes accepted context/provenance, not a demonstrated complete answer.

Evidence: [local_documents.py:60](C:/ai-financial-wellness-coach/apps/ai-service/app/rag/local_documents.py:60), [local_documents.py:137](C:/ai-financial-wellness-coach/apps/ai-service/app/rag/local_documents.py:137), [retriever.py:91](C:/ai-financial-wellness-coach/apps/ai-service/app/rag/retriever.py:91), [retriever.py:150](C:/ai-financial-wellness-coach/apps/ai-service/app/rag/retriever.py:150), [education_access.py:176](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/education_access.py:176).

Change direction: budget relevant passages by requested subquestion using tokens, preserve list/table structure, and distinguish provenance success from coverage/answerability. Measure these changes against the existing governed corpus.

### A24 — P3: provenance presentation and citation grammar constrain natural formats

**Reproduced citation rejection; code-confirmed presentation.** Any ordinary remaining square bracket is rejected as an unapproved citation: `Use [food] as a placeholder category` fails. JSON repair asks the model to remove such syntax. Education output adds fixed source/model-knowledge sections, turns unsourced sections into bullets, and wraps requested tables in generated tables by joining lines. Inline citation rendering appends filenames/document types to source links.

These choices protect evidence attribution, but also add repeated technical labels and constrain how analogies, placeholders, mixed-format explanations and tables can be expressed. The frontend otherwise preserves assistant content; ordinary currency escaping and whitespace trimming are not the main cause.

Evidence: [citations.py:32](C:/ai-financial-wellness-coach/apps/ai-service/app/core/citations.py:32), [citations.py:55](C:/ai-financial-wellness-coach/apps/ai-service/app/core/citations.py:55), [investment_education.py:269](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/investment_education.py:269), [investment_education.py:287](C:/ai-financial-wellness-coach/apps/ai-service/app/agents/investment_education.py:287).

Change direction: validate actual citation tokens/links separately from harmless punctuation and render concise provenance in the UI. Preserve the distinction between sourced and model-only claims without forcing the same explanatory layout for every question.

### A25 — P1 if assessing default local launch: Compose runs an offline fixture

**Configuration-dependent.** Compose loads `.env.example` and explicitly sets `MODEL_PROVIDER: local_fixture`. The example also selects fixture retrieval. The fixture gateway routes by rules and synthesizes by joining specialist summaries. Adding an API key or changing host model settings alone does not change this Compose configuration.

AWS source configuration selects OpenAI, `gpt-6-luna`, low reasoning, v6 prompts, local-document retrieval and 1,600 output tokens. The actual runtime/deployment was not inspected; do not infer fixture use in AWS from the local defaults.

Evidence: [docker-compose.yml:23](C:/ai-financial-wellness-coach/docker-compose.yml:23), [gateway.py:226](C:/ai-financial-wellness-coach/apps/ai-service/app/models/gateway.py:226), [.env.example:37](C:/ai-financial-wellness-coach/.env.example:37), [demo-application.yaml:321](C:/ai-financial-wellness-coach/infra/aws/demo-application.yaml:321).

Change direction: expose an unambiguous live/fixture indicator and an explicit local live-model launch configuration. Verify provider/model/prompt identity from actual request traces before judging model quality.

### A26 — P2: model controls and structured-output recovery have hidden limits

**Code-confirmed; live quality/latency effect not measured in this audit.**

- The same gateway/model/reasoning effort and 1,600-token output budget serve routing, specialists, synthesis and compliance. There is no role-specific model/reasoning/output-budget selection.
- Router/agent/compliance temperature settings exist, but the OpenAI adapter explicitly deletes `temperature`. Tuning these knobs has no effect on the active OpenAI path; the correction attempt's reduced temperature is also ineffective there.
- The adapter asks for JSON-object output, while typed schema/citation/provenance validation occurs afterward. The complete JSON Schema is added on a correction attempt rather than supplied as the initial output contract.
- Correction retries only a small list of error codes. For example, `INVALID_EDUCATION_PROVENANCE` and `UNAPPROVED_EDUCATION_TOPIC` do not use that correction path. A correction uses the same output cap and does not carry the actual failed draft, making it a fresh constrained generation.
- Incomplete/empty output and most provider failures collapse to `OPENAI_INVOCATION_FAILED`; the adapter does not retain separate incomplete reasons or reasoning-token details. This limits diagnosis of budget exhaustion versus service failure.
- Source defaults/releases still select v6; the existence of v7 does not mean it is active, and v7 retains several of the same specialist instructions. Merely switching versions is not a complete remedy.

Evidence: [config.py:16](C:/ai-financial-wellness-coach/apps/ai-service/app/core/config.py:16), [config.py:33](C:/ai-financial-wellness-coach/apps/ai-service/app/core/config.py:33), [gateway.py:180](C:/ai-financial-wellness-coach/apps/ai-service/app/models/gateway.py:180), [gateway.py:197](C:/ai-financial-wellness-coach/apps/ai-service/app/models/gateway.py:197), [structured.py:64](C:/ai-financial-wellness-coach/apps/ai-service/app/models/structured.py:64), [orchestrator.py:241](C:/ai-financial-wellness-coach/apps/ai-service/app/orchestrator.py:241), [release.yml:402](C:/ai-financial-wellness-coach/.github/workflows/release.yml:402).

Change direction: configure/measure each role's reasoning and output budget, remove misleading unsupported knobs, use explicit typed output contracts, and record actionable failure reasons. Compare live models only after addressing the deterministic data-flow failures.

### A27 — P2: passing regression tests do not establish conversational quality

**Code-confirmed.** CI's LLMSecOps gate creates `LocalFixtureModelGateway` explicitly. Many checks validate agent sets, flags, source IDs and calculation fields. Some tests intentionally enforce current rigid choices, including rejecting conversational language changes. The targeted Spending analyzer tests pass despite the calendar-boundary defect in A09.

The repository already contains live-evaluation, representative-user and human/model-assisted answerability tooling. The gap is that the routine fixture/structural gate cannot certify a helpful live conversation, and the reproduced cross-layer scenarios are not established by that gate. This audit did not inspect remote workflow results or claim that no live reviews have occurred.

Evidence: [runner.py:227](C:/ai-financial-wellness-coach/apps/ai-service/app/evals/runner.py:227), [runner.py:58](C:/ai-financial-wellness-coach/apps/ai-service/app/evals/runner.py:58), [ci.yml:109](C:/ai-financial-wellness-coach/.github/workflows/ci.yml:109), [rag_answer_review.py:378](C:/ai-financial-wellness-coach/apps/ai-service/app/evals/rag_answer_review.py:378).

Change direction: add end-to-end adversarial paraphrase, multi-intent, follow-up-format, period-boundary and context-continuity cases; use the existing live/answerability tooling to score directness, useful next steps, repeated questions, format/language compliance and unnecessary refusals.

### A28 — P2/P3: duplicated intent/date rules make behavior inconsistent across layers

**Code-confirmed; selected parsing examples reproduced above.** Intent detection is repeated in frontend question templates, backend early returns, workspace evidence selection, session memory, orchestration, capture agents, fixtures and compliance. A model-selected intent can therefore encounter a different parser's interpretation later. Backend workspace construction also hides goals/settings/reconciliation or historical spending according to independent keyword matches, so relevant evidence may be absent before the model runs.

UTC is used for transaction `today`, default budget month and default AI spending period, while budget planning uses Asia/Singapore. During the first eight hours of a Singapore day/month, temporal interpretation can disagree across handlers.

Evidence: [budget_planning.py:56](C:/ai-financial-wellness-coach/apps/backend/app/services/budget_planning.py:56), [budget_workspace.py:49](C:/ai-financial-wellness-coach/apps/backend/app/services/budget_workspace.py:49), [transaction_capture.py:309](C:/ai-financial-wellness-coach/apps/backend/app/services/transaction_capture.py:309), [routes.py:63](C:/ai-financial-wellness-coach/apps/backend/app/api/routes.py:63), [spending_analyzer.py:318](C:/ai-financial-wellness-coach/apps/ai-service/app/tools/spending_analyzer.py:318).

Change direction: carry one typed turn intent, query scope, reference resolution and user-local as-of date through the pipeline. Keep domain validation local, without reclassifying the conversational request by prose at every stage.

## Recommended order

1. **Fix correctness and action integrity first:** A09 monthly boundaries, A11 range queries, A12 query filters, A13 forecast semantics, A14 chat-bound confirmations, A08 analysis inputs.
2. **Restore conversational continuity:** A01 status hijacking, A05 local-reply provenance, A04 follow-up subjects, A06 memory, A07 saved preferences.
3. **Simplify turn execution:** separate explanation/hypothesis/query/proposed mutation; stop unrelated pending drafts from forcing capture; narrow missing-input requirements (A02/A03/A28).
4. **Compose the answer after validated outcomes:** structured backend results followed by a single localized, intent-appropriate answer; remove repeated essay instructions and contradictory save claims (A15–A18).
5. **Narrow excessive refusals and format restrictions:** A19–A24 while retaining ownership, source integrity, actual credential protections and prohibited investment-product advice controls.
6. **Measure live behavior before tuning the model:** verify live/fixture identity, instrument failure reasons, introduce role-specific budgets, and run existing quality tooling with the cross-layer cases (A25–A27).

## Validation record

Local audit probes exercised guardrail vocabulary, monetary redaction, household privacy matching, ordinary bracket citation validation, education-topic/query construction, lexical retrieval, monthly trend boundaries, sparse-data quality, follow-up formats, forced routing, specialist preflight, profile propagation, backend early-return/context flow, period/filter queries, recurring forecasts, cross-chat confirmations, and post-AI localization. Backend mutation probes used disposable in-memory SQLite only; model behavior was scripted or mocked.

Existing checks run during this audit:

- AI service: `test_model_gateway.py`, `test_passage_ranking.py`, `test_retriever.py`, `test_request_retrieval_cache.py`, `test_spending_analyzer.py` — **48 passed**. Pytest reported a cache-write permission warning; tests completed successfully.
- Backend context/summary/staging/budget-alert tests — **80 passed**.
- Frontend tests enforcing workspace locale over input/profile requests — **2 passed**.

These 130 passing tests are evidence of the existing contract, not proof that the reproduced gaps are acceptable. No paid/live model calls, deployments, production data changes, full test-suite run or remote operational checks were performed.

## Boundaries worth preserving

Deterministic arithmetic, authenticated ownership, typed financial/currency validation, exact previews/confirmation before record changes, approved-source metadata/checksums, citation integrity, and independent compliance are useful controls. Ordinary `.strip()`, source-title escaping, currency Markdown handling and presentation localization are not inherently reasoning defects.

Several legacy transaction parsers and fixture implementations contain rigid grammar that is not the main current recording path. The active `handle_transaction_capture` explicitly retains edit/delete/last-saved helpers; do not fix every old parser on the assumption that it governs live capture. The priority is the reachable Coach data flow and the reproduced outcomes above.
