# Prompt Set v6

Version 6 preserves the five-agent workflow and v5 structured Investment output.
It adds canonical fine-grained topics and question intent, explicit partial-evidence
handling, and source markers rendered by the application rather than model-generated links.
Compliance reviews the final answer and specialist rationale/uncertainty against the
actual evidence, including unsupported subtopics, and distinguishes risk education
about return guarantees from promises or product-selection requests.

The source and deployment templates target v6. Offline regression evidence does not
establish live model grounding, retrieval quality, or deployed state; repeat the live
Bedrock evaluation for this prompt set before accepting those behaviors.
