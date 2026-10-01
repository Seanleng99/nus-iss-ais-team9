# Coach session context

The Coach uses two complementary forms of context within an owned conversation:

- The latest eight messages, capped at 1,500 characters each, retain recent dialogue.
- Backend-owned structured state retains supported user-reported details, their source message positions, corrections, the active topic and pending clarification fields.

This is derived chat state, not cross-chat durable agent memory. It has the same ownership, 90-day inactivity retention, export and deletion boundary as its chat. It never writes profile income, goals, budgets or transactions. Saved records and deterministic grounding remain authoritative for financial calculations; normal previews and confirmations still govern draft changes.

## Supported facts and examples

The first-stage extractor intentionally accepts explicit forms and single-field clarification answers. General natural-language understanding continues to use recent dialogue; arbitrary statements are not converted into long-term facts by a model.

| Field | Explicit example |
|---|---|
| Monthly income | `My monthly income is SGD 5,000.` |
| Monthly expenses | `My monthly expenses are 2,000.` |
| Goal name | `My goal name is Holiday.` |
| Goal target | `My goal target amount is 1,200.` |
| Current savings | `My current savings is 200.` |
| Goal duration | `My goal duration is 12 months.` |
| Budget month | `My budget month: September 2026` |

Basic Chinese labels such as `我的每月收入是5000` are also recognized. Bare amounts and `$` use the application's fixed SGD currency. Explicit foreign currencies, negative values, conditional examples, third-party statements and unsafe messages do not produce supported facts. Multiple conflicting values are marked uncertain rather than selected. Values are bounded and schema-validated at the AI boundary.

Immediately after stating one supported field, `Actually, it's 4200.` replaces that field and records which source position it supersedes. If the Coach is waiting for exactly one monetary field, `4200` can answer it. A bare number never chooses among multiple pending fields. A later explicit field statement can resolve uncertainty. Source positions refer to the original user messages in the retained chat.

## Behavior

- Financial reply writers acknowledge remembered details and corrections as user-reported. Their calculation grounding is unchanged.
- Goal Strategy clarification acknowledges previously supplied income, goal amount and duration. If a saved record is required, it explains that requirement instead of asking for the same amount again.
- `What did I tell you about my income?` recalls supported facts in this chat and explicitly identifies them as unconfirmed chat details.
- After a local date-spending query, `What about 21/9?` continues that topic using owned transaction records. A fresh chat or unrelated topic does not inherit that query.
- A budget-status question with an explicit month uses that month. `Am I over budget for that month?` can refer to a previously stated budget month.
- An unknown or ambiguous budget month requires clarification. After `Which month and year does that budget refer to?`, a short answer such as `September 2026` resumes the local read-only status check.
- Recognized fact answers and corrections are not routed into automatic expense capture. Transaction amount/date clarification queues are separately scoped to the user and chat; their existing process-local storage and ten-minute expiry remain.
- Facts are committed together with a successful chat exchange. Failed and blocked replies do not commit new facts. Legacy chats bootstrap supported facts from at most the latest 64 messages, excluding blocked turns; subsequent compact state persists with the chat.

## Rollout and validation

Apply `alembic upgrade head` in `apps/backend` before running the updated backend, then deploy the backend and AI service together. Compose runs migrations automatically. This change does not require a frontend change.

Backend regressions cover source attribution, corrections, recall beyond the recent-message window, isolated chats/owners, client-forged context, ambiguous input, failed/blocked replies, local follow-ups, export/deletion and transaction clarification isolation. AI regressions cover preflight acknowledgment, context-aware fixture routing, role minimization, schema validation and unchanged calculation grounding. These offline tests do not establish live-model recall quality; verify representative multi-turn conversations after deployment using synthetic inputs and automatic agent routing.

Older-message summarization, arbitrary natural-language fact extraction, a session-state editing UI and cross-chat memory are deferred. The ordinary local fixture still produces deterministic narratives; its limited follow-up routing is for regression coverage, not a substitute for live-model behavior.
