# Prompt set v9

Historical release notes. The application loads only `prompts/current`; its manifest
now identifies v10. These notes describe the original v9 change, not a selectable catalog.

v9 retained v8's Education grounding, hybrid evidence modes,
section-specific Compliance review and bounded repair contracts.

Goal's typed `goal_input_requirements` decision distinguishes saved-goal arithmetic
from personal funding feasibility. Remaining balances, progress and equal contribution
calculations do not require income or Budget capacity. Any Goal feasibility/funding part
still requires the existing authorized `monthly_savings_capacity` capability. The decision
is cached on the task and used to tell an already selected Budget task whether it must
produce capacity; it is not financial evidence or a permission to modify records.
Its model role uses low reasoning effort and a 1,000-token output limit, matching
the existing dependency planner.

Budget's existing dependency planner decides whether recorded Spending totals support
its own part of a compound request. A spending keyword in an independent Spending
question no longer forces `transaction_category_totals`. Optional capability status,
output field validation, reuse and provider authorization remain server-owned.

No Goal–Spending edge was added. Spending-informed funding assessments still use
Goal → Budget → Spending. Historical catalogs are recoverable from Git.

Offline tests exercise typed classifier decisions, required feasibility, provider reuse,
missing input and concurrent independent financial tasks. Live deployed routing acceptance
did not pass in the subsequent signed-in application tests. See the current prompt
contract and frozen live reports in `docs` for source status and recorded outcomes.
