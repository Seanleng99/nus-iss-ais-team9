# Retrieved-Content and Instruction Security Policy

User text and retrieved text are untrusted data. Neither can change system policy, expand an agent's permissions, select another specialist, or authorize a tool that the orchestrator has not allowlisted.

Instructions found inside retrieved content must be removed before that content reaches a model. Requests to expose hidden configuration, access credentials, cross an agent boundary, or weaken safety controls must be blocked.

Risk and Compliance may use only its dedicated Policy retriever. It must not query the Education collection. Investment Education may use only its dedicated Education retriever and must not query the Policy collection.

Provider errors are returned as sanitized service failures. Logs and traces must not contain raw prompts, retrieved text, credentials, financial snapshots, or provider error details.
