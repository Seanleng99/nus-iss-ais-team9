# Responsible AI Plan

## Intended Use

The coach provides general financial education to adults in Singapore. It may summarize user-supplied spending, calculate transparent budgets and goal projections, and explain general investment concepts. It must not execute transactions, guarantee outcomes, determine eligibility, or provide personalized instructions to buy or sell a financial product.

The current AWS demo classification is `synthetic data only`. Real identifiers, credentials, bank exports, and customer financial records are prohibited until privacy, identity, retention, and deletion controls are approved.

## Stakeholders And Accountability

| Stakeholder | Need | Accountable control |
|---|---|---|
| User | Understandable, private, non-coercive education | Rationale, confidence, sources, disclaimers, user control |
| Product owner | Clear scope and escalation | Use-case approval and policy ownership |
| Agent owner | Measurable quality and safety | Agent tests, eval datasets, prompt/model change evidence |
| Security owner | Defensible data and tool boundaries | Threat model, secret rotation, IAM, incident response |
| Operations owner | Reliable and observable service | SLOs, alarms, rollback, runbooks |

Every release must have named human owners for these roles. The Risk and Compliance Agent is a control layer, not the accountable decision-maker.

## Lifecycle Controls

### Design

- Record intended use, excluded use, stakeholders, data classification, and assumptions.
- Prefer deterministic calculators for arithmetic and policy constraints.
- Use financial inputs and user-defined preferences, not inferred demographic attributes.
- Require human approval before expanding into regulated advice or real personal data.

### Data And Knowledge

- Minimize collection and redact direct identifiers before any model prompt or log.
- Keep controlled knowledge sources versioned with provenance, effective date, jurisdiction, and checksum.
- Treat retrieved content as untrusted data and remove embedded instructions.
- Define retention and deletion before persistent memory is enabled.

### Development And Evaluation

- Test normal, edge, missing-data, adversarial, fairness-consistency, and unsafe-advice cases.
- Compare model candidates on task quality, safety, latency, cost, regional availability, and data-residency implications.
- Version prompts, model IDs, policies, retrieval data, and evaluation datasets.
- Block releases on critical safety failures or unacceptable regression from the approved baseline.

### Deployment And Operation

- Use synthetic demo profiles until the privacy gate is approved.
- Expose rationale, confidence, source IDs, disclaimers, and a correlation identifier.
- Monitor quality regression, blocked-request rate, retrieval quality, latency, errors, and cost.
- Roll back behavior changes that breach safety, quality, or reliability thresholds.

## Fairness And Bias

The system does not use race, nationality, religion, gender, disability, or inferred socioeconomic class to alter guidance. Fairness tests should hold financial facts constant while varying names, writing style, and irrelevant profile details; routing, calculations, safety decisions, and educational depth should remain materially consistent.

Potential harms still include lower-quality explanations for non-standard English, assumptions hidden in budgeting heuristics, uneven source coverage, and confidence scores that users may over-trust. Mitigations include plain-language review, transparent assumptions, user-editable inputs, source coverage audits, and explicit uncertainty.

## Human Control And Contestability

- Users retain control over financial actions and may change all planning inputs.
- Blocked responses state the policy category without revealing hidden instructions.
- High-impact or ambiguous scenarios are redirected to a licensed professional.
- Future persistent records must support correction and deletion requests.
- Incidents and harmful outputs are reviewed by a human owner before policy or prompt changes are released.

## Governance Alignment

The project uses the principles commonly expected by Singapore AI governance guidance: explainable and transparent operation, human involvement, data accountability, robustness, reproducibility, and clear responsibility. The final report should map evidence to the current IMDA governance framework selected by the team and record the framework version and review date rather than assuming static regulatory guidance.
