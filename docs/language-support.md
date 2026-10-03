# Chinese language support

Coach uses one agent workflow, one set of financial tools and one set of ownership checks for English and Simplified Chinese. Reviewed messages and recognition resources live in the shared `coach-i18n` package under `apps/shared`. Additional languages extend these resources and acceptance cases without copying agents, calculations or persistence code.

## Explicit application language

The globe icon immediately left of the three-dot menu opens the workspace language selector. It offers English (`en`) and Simplified Chinese (`zh-Hans`) on every page, including sign-in. The setting is shared across profiles and controls navigation, headings, forms, reviewed status messages, charts, Coach controls, source labels and the language requested from the agents. Coach has no separate response-language selector or automatic mode.

The browser starts in English unless its URL explicitly selects an allowlisted locale through `coach_language=en` or `coach_language=zh-Hans`. Session state retains the choice across navigation and profile switches, and navigation restores the URL parameter so a reload retains the choice. Stable form keys retain unsaved profile inputs when labels change. Selecting a language does not update the financial profile.

The frontend always sends an explicit `response_locale` with each Coach request. That setting has precedence over the saved profile preference. Neither the current message, conversation history, session summaries nor retrieved text can select another language. With English selected, Chinese input or an English request to answer in Chinese still receives English. With Chinese selected, a request inside the conversation to answer in English cannot change the setting.

API callers can also supply `response_locale`. When omitted, an owned saved profile preference is used when supported; otherwise the default is English. Legacy labels such as `English`, `Chinese` and `Mandarin` normalize to the supported tags. Unsupported explicit API locales are rejected. This compatibility fallback never detects the language of conversation text.

## Agents, data and display

The backend resolves the locale before dispatch. Each restricted specialist receives only the selected locale alongside its existing context. Specialist, synthesis and independent review instructions make the application setting authoritative over language requests in untrusted text. Existing `response_language` audit values remain `English` or `Chinese`; `response_locale` records the locale tag.

Current interface labels follow the selection, including labels around historical responses. Existing user and assistant messages keep their saved text. Generated prose is written by the model in the selected language and is not translated at the display boundary. Original source titles, organizations, URLs, filenames, source IDs and trace IDs retain their source identity.

Reviewed refusals, evidence gaps, income-memory responses, clarification prompts, provenance labels and disclaimers use keyed JSON catalogs. Blocked model drafts are never translated into publishable content. Citation, evidence, safety and ownership validation apply in both languages. Retrieval uses canonical topic identifiers, and bilingual aliases live in recognition resources.

Interface options are translated for presentation while requests and stored enum/category identifiers stay canonical. Amounts, calculations and user-authored names and descriptions are preserved. Presentation tables use copies with localized headings. Chinese month labels use numeric `YYYY-MM` formatting.

Application-owned labels on Overview, Transactions, Budget, Goals, Coach, Profile, Create profile, sign-in and decision traces use reviewed translations. Framework controls such as Streamlit's built-in menu, calendar, chart tools and file controls may retain their framework language. Backend transaction, budget and goal-management receipts are not yet fully cataloged; these legacy deterministic workflows need further reviewed templates for complete Chinese coverage. Arbitrary backend validation text and historical prose are not automatically translated. Deployed-provider acceptance tests are still required to establish live-model language compliance; offline fixture tests do not certify it.

## Resources and verification

Chinese text and Han Unicode escapes are confined to JSON resources and datasets. Messages live in `locales/zh-Hans.json`, with matching keys and interpolation fields in `locales/en.json`. Bilingual input and safety patterns live in `data/input_patterns.json`, intent terms and ordinal mappings in `data/input_vocabulary.json`, and script ranges in `data/scripts.json`. Input recognition is independent of output language, so English selection cannot disable Chinese safety checks. Traditional Chinese inputs remain recognized; no separate Traditional Chinese output catalog is provided.

Independent Chinese inputs and golden assertions live in each service's `tests/fixtures/language_cases.json`; evaluation questions remain in JSONL. Cases requiring Chinese output explicitly select `zh-Hans`. Tests cover contradictory chat language requests, shared selection across pages and profiles, URL reloads, translated forms saving canonical values, preservation of unsaved profile inputs, and catalog interpolation parity. The evaluation gate checks generated fixture answers as well as audit metadata. Developer documentation is in English.

Install the shared package with each service, for example `pip install -e apps/shared -e "apps/ai-service[dev]"`. Container builds and CI install the package and include its resources. Shared-package changes select all services in the CI/CD change classifier.

Run `python scripts/scan_chinese.py --output docs/chinese-character-inventory.json --markdown docs/chinese-character-inventory.md --check-code` to scan tracked and non-ignored project text files. The inventory records paths and literal/escape line numbers without copying source contents. `--check-code` fails on Han literals or escapes in Python, JavaScript, TypeScript or shell code; CI runs this check. Ignored environments, binaries and generated artifacts are excluded. See [the inventory summary](chinese-character-inventory.md) and [matching line numbers](chinese-character-inventory.json).
