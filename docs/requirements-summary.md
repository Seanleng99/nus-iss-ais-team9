# Requirements Summary

Source documents reviewed from the module `/docs` folder:

- AAS Practice Module Briefing.pdf
- AAS Practice Module FAQ.pdf
- AAS Practice Module Project Proposal Team 9.pdf
- AAS Practice Module Project Proposal Team 9 Feedback.txt

## Project Intent

AI Financial Wellness Coach is a multi-agent financial education platform for young adults in Singapore, aged 18 to 35. It helps users understand spending, create budgets, plan goals, and learn investment concepts. It must remain educational and advisory, not regulated financial advice.

## Module Expectations

The project should demonstrate competency in:

- Explainable and responsible AI.
- AI cybersecurity.
- Agentic AI architecture and orchestration.
- Integration, deployment, MLSecOps, and LLMSecOps.

The report and demo should cover logical and physical architecture, deployment strategy, agent communication, model choices, memory, tools, responsible AI practices, risk register, CI/CD, monitoring, auditability, and evaluation results.

## Team 9 Proposed Scope

The original proposal defines:

- Angular frontend on S3 and CloudFront.
- Spring Boot backend on ECS.
- Python AI agent service on ECS.
- LangGraph-style Agent Orchestrator.
- Amazon Bedrock as model provider.
- PostgreSQL for transactional data.
- Vector database for trusted RAG content.
- MAS, CPF, and financial literacy resources ingested offline.
- AWS Secrets Manager and CloudWatch.

## Revised Implementation Decision

The implementation replaces Angular and Spring Boot with three Python services:

- Streamlit frontend on ECS Fargate.
- FastAPI application backend on ECS Fargate.
- Private FastAPI multi-agent service on ECS Fargate.

This preserves independent presentation, application, and AI boundaries while reducing language overhead. The backend owns profiles, transactions, monthly budgets, goals, dashboard summaries, coaching snapshots, and persistence, with end-user identity still planned. The Streamlit frontend exposes those workflows as a multipage financial workspace. The AI service owns orchestration, RAG, model access, guardrails, and evaluation. This is consistent with the module FAQ, which permits a simple UI and expects architecture choices to be justified.

## Agents

- Spending Agent
- Budget Agent
- Goal Strategy Agent
- Investment Education Agent
- Risk & Compliance Agent

## Feedback Incorporated

The skeleton addresses the project feedback by:

- Applying PII detection, schema validation, prompt-injection checks, RAG document sanitization, and tool permission allowlists across all agents and service boundaries.
- Defining eval datasets for orchestrator routing, budget calculations, and RAG retrieval relevance.
- Capturing expected outputs, metrics, and acceptance criteria in `docs/evaluation-plan.md`.
- Adding an ADR on MCP and A2A relevance.
