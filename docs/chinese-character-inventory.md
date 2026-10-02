# Chinese-character inventory

Scanned 451 tracked and non-ignored UTF-8 text files at `working_tree`; 18 files contain Han characters or Unicode escapes representing them.

Literal characters and escaped code points are reported separately. Han script is also used by Japanese and other languages; this inventory identifies characters, rather than asserting the language of every string. Ignored environments, generated artifacts and binary files are excluded. No source contents are copied.

Developer documentation is English. Chinese display text, input recognition and safety rules live in shared JSON resources. Test questions and golden assertions live in independent JSON fixtures and evaluation datasets. This scan found 0 code files with Han literals or escapes.

| Category | Files |
| --- | ---: |
| evaluation datasets | 7 |
| language resources | 7 |
| test fixtures | 4 |

See [the JSON inventory](chinese-character-inventory.json) for every matching line number. Regenerate with `python scripts/scan_chinese.py --output docs/chinese-character-inventory.json --markdown docs/chinese-character-inventory.md --check-code`.

| File | Category | Literal lines | Escaped lines |
| --- | --- | ---: | ---: |
| [apps/ai-service/app/evals/datasets/investment_answerability_v1.jsonl](../apps/ai-service/app/evals/datasets/investment_answerability_v1.jsonl) | evaluation datasets | 141 | 0 |
| [apps/ai-service/app/evals/datasets/investment_answerability_v2.jsonl](../apps/ai-service/app/evals/datasets/investment_answerability_v2.jsonl) | evaluation datasets | 141 | 0 |
| [apps/ai-service/app/evals/datasets/investment_answerability_v2.manifest.json](../apps/ai-service/app/evals/datasets/investment_answerability_v2.manifest.json) | evaluation datasets | 3 | 0 |
| [apps/ai-service/app/evals/datasets/rag_evidence_v1.jsonl](../apps/ai-service/app/evals/datasets/rag_evidence_v1.jsonl) | evaluation datasets | 50 | 0 |
| [apps/ai-service/app/evals/datasets/rag_retrieval.jsonl](../apps/ai-service/app/evals/datasets/rag_retrieval.jsonl) | evaluation datasets | 3 | 0 |
| [apps/ai-service/app/evals/datasets/security_guardrails.jsonl](../apps/ai-service/app/evals/datasets/security_guardrails.jsonl) | evaluation datasets | 2 | 0 |
| [apps/ai-service/tests/fixtures/language_cases.json](../apps/ai-service/tests/fixtures/language_cases.json) | test fixtures | 85 | 1 |
| [apps/backend/tests/fixtures/language_cases.json](../apps/backend/tests/fixtures/language_cases.json) | test fixtures | 16 | 0 |
| [apps/frontend/tests/fixtures/language_cases.json](../apps/frontend/tests/fixtures/language_cases.json) | test fixtures | 3 | 0 |
| [apps/shared/coach_i18n/data/education_vocabulary.json](../apps/shared/coach_i18n/data/education_vocabulary.json) | language resources | 152 | 0 |
| [apps/shared/coach_i18n/data/input_patterns.json](../apps/shared/coach_i18n/data/input_patterns.json) | language resources | 87 | 1 |
| [apps/shared/coach_i18n/data/input_vocabulary.json](../apps/shared/coach_i18n/data/input_vocabulary.json) | language resources | 13 | 0 |
| [apps/shared/coach_i18n/data/language_requests.json](../apps/shared/coach_i18n/data/language_requests.json) | language resources | 2 | 0 |
| [apps/shared/coach_i18n/data/offline_education_zh.json](../apps/shared/coach_i18n/data/offline_education_zh.json) | language resources | 6 | 0 |
| [apps/shared/coach_i18n/data/scripts.json](../apps/shared/coach_i18n/data/scripts.json) | language resources | 0 | 3 |
| [apps/shared/coach_i18n/locales/zh-Hans.json](../apps/shared/coach_i18n/locales/zh-Hans.json) | language resources | 47 | 0 |
| [apps/shared/tests/fixtures/language_cases.json](../apps/shared/tests/fixtures/language_cases.json) | test fixtures | 8 | 0 |
| [infra/llmsecops/budget-live-evaluation-cases.jsonl](../infra/llmsecops/budget-live-evaluation-cases.jsonl) | evaluation datasets | 1 | 0 |
