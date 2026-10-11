# Current prompt contract

The application and executable evaluations use one supported prompt contract. The
catalog loads `apps/ai-service/prompts/current/prompts.json`; its adjacent
`manifest.json` names the release (`v10` after the 9 October Risk & Compliance update). This designation is explicit
and packaged with the application. It does not search for the highest numbered
folder or fetch prompts during a request.

The 11 October fairness increment appends a shared fairness policy to every
effective prompt and adds a typed `demographic_assumption` Compliance finding.
The v10 manifest remains the catalog release label; the changed effective
prompt-content hash identifies the amended instructions. Located claim removal
can use the existing bounded correction path only with a new allowed full review.
See [fairness testing](fairness-testing.md) for source-level controls and the
separate live and human-review evidence requirements.

Routing, task assignments, conditional financial dependencies, hybrid Education
grounding, scoped compliance review and bounded correction all use the current
behavior. There are no prompt-version switches in those paths. Goal contribution
arithmetic remains independent; Goal feasibility requests Budget capacity. Budget
requests Spending only when its own assigned question needs transaction evidence.
The direct Goal-to-Spending capability remains deferred.

Explicit specialist selection constrains the model's initial plan and task
assignments. A mismatched plan receives one bounded correction with the actual
contract error. Budget/Goal keep the educational parts they own and may request
Education context; an unselected primary specialist cannot take those parts and
then disappear when the selection is applied. Declared record operations still
require their owning specialist. Automatic routing continues to split independent
questions among the appropriate specialists when no selection is supplied.

`PROMPT_SET_VERSION` is optional. If a deployment supplies it, configuration loading
checks that it matches the packaged manifest once. It cannot select an old behavior.
Local defaults and the bootstrap task omit it; the release workflow derives its
assertion from the manifest and verifies the rendered ECS definition. A stale
inherited value is replaced before release.

Every response audit and workflow trace identifies the prompt release, a SHA-256
hash of the effective prompt content (including the shared currency policy), and
`BUILD_COMMIT`. Releases inject the Git commit; local builds report `unknown` unless
explicitly identified. These are provenance fields, not routing rules. Private
Education and financial grounding snapshots bind correction to the same prompt
identity as well as the original question, task and evidence. Changing instructions
under the same release label invalidates reuse.

Behavior tests run against the current catalog once, with cases parametrized by
meaningful inputs and failure conditions. Evaluation profiles distinguish providers,
not historical prompt versions; current answerability captures also pin the complete
bounded runtime and role policies. Comparing capture/review identities still rejects
mixed or stale evidence. Dataset and corpus versions remain separate evidence
contracts and are not removed by this simplification.

The Promptfoo security adapter uses the same packaged defaults in offline and live
mode. Its direct compliance reviewer also loads the current catalog. Provider
regressions cover both setup paths without invoking a paid model, so an obsolete
adapter override cannot silently prevent the security checks from running.

Historical prompt files are recoverable from Git rather than shipped as selectable
runtime catalogs. Historical reports remain evidence of their recorded revisions;
they do not establish acceptance of the current implementation. To reproduce an old
run, check out its exact commit with its then-current prompts, dependencies and
evaluation protocol. New releases require fresh evaluation evidence.

To update prompts, edit the current catalog and run the current regressions and
relevant model evaluations. The effective content hash identifies every instruction
change; coordinate the manifest label when naming a new release. Runtime code does
not need a new version allowlist or branch.

The latest v10 [local claim recovery](orchestration-local-claim-recovery-2026-10-09.md)
adds a replacement-only correction role and clarifies exact spending movement and
per-part coverage. It keeps the release label and computes the effective content
hash from current instructions. App, tests and deployment role configuration use
that same catalog and policy.

The original v10 change removes the obsolete minimal Compliance JSON example in favor of
the actual supplied schema. It retains the single current catalog, routing and
dependency behavior. The reviewed Policy corpus has its own version,
`financial-coach-policy-sg@2026-10-09.1`; its meaning is also used by offline
fixtures, with a separate synthetic lifecycle. Changes are local until released
and evaluated with the deployed model.

Historical offline validation of the preceding catalog on 2026-10-08 passed 1,805 AI-service tests (one skipped), 942
backend tests, 46 shared tracing tests, and 331 infrastructure tests (five skipped,
16 subtests passed). The final focused check passed 169 tests. Lint, the language
source scan, and prompt packaging checks passed. These offline checks do not
establish production-model acceptance. The release workflow separately verifies
deployed model behavior, conditional source retrieval and persisted trace
provenance; its deployment job records the current release outcome.

The v10 [9 October verification](risk-compliance-review-update-2026-10-09.md)
passed 1,883 AI-service tests (one platform skip), 64 shared tests, 22 backend
trace/storage tests, 40 frontend tests, 99 release/evaluation configuration tests
and all 87 offline evaluation cases. It also verified active configuration and
current docs against the manifest. Frozen prior-release reports retain their
observed prompt version; no deployed v10 model acceptance is claimed.
