# Container Security Exception Review

## 2026-10-01 Release Blocker — Approved Temporary Exception

**Status: approved 2026-10-01 by the repository owner in this Codex conversation.**
The owner explicitly accepted the exact AI-image exception and then extended
approval to the backend and conditionally to an identical frontend finding,
through 2026-10-08, authorizing committing, pushing and retrying deployment. Native
dependency reachability remains unverified; approval accepts that residual risk.

[Release run 36803604113](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36803604113)
for `2bcf575bdf278599130f86a062d0fd41a04aa174` built and published the images,
then stopped at the ECR/Inspector gate before migrations or ECS deployment.
[CI run 36803327539](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36803327539)
passed. The completed AI-image scan reported one unexcepted HIGH finding:
`CVE-2026-102010`, source package `gcc-14`, version `14.2.0-19`, CVSS 3 score 7.0.
The existing zlib exception matched; no exception then covered this GCC finding.
The gate stopped at the AI image, so this run does not establish backend or
frontend scan acceptance.

As checked on 2026-10-01, the [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-102010)
lists Trixie's `gcc-14 14.2.0-19` as vulnerable, with no fixed Debian version.
It also lists GCC packages in Bookworm and unstable as vulnerable. Re-running
the release reuses the immutable images and does not supply a package fix.
All three Dockerfiles already run `apt-get upgrade`.

The [upstream fix](https://github.com/gcc-mirror/gcc/commit/aaa8351f4d2e636f9680a1f0a8ebc2f0a60611e6)
updates `m_a_entries` after reallocation in the C++ header
`ext/pb_ds/detail/binary_heap_/erase_fn_imps.hpp`. Exploitation requires an
application to invoke that binary heap's `erase_if` operation. Repository
application code is Python and does not directly use this operation. This is
limited exposure evidence, not proof that compiled third-party wheels cannot
contain it. Patching an installed header alone would not repair a wheel that
already compiled the vulnerable template. Local container inspection is also
unavailable because the Docker daemon is not running.

### Approved temporary exception

This exact exception is recorded in `infra/llmsecops/ecr-scan-exceptions.json`
and is loaded by the release gate. It expires after 2026-10-08.

| Field | Approved value |
|---|---|
| CVE | `CVE-2026-102010` |
| Source package/version | `gcc-14` / `14.2.0-19` |
| Repositories | `nus-iss-ais-team9-ai`, `nus-iss-ais-team9-backend`, `nus-iss-ais-team9-frontend` (identical finding only) |
| Review date | 2026-10-01 |
| Expiry | 2026-10-08 |
| Reviewer | Repository owner; explicit approval in the Codex conversation |
| Scope | Existing synthetic-data demo only |
| Rationale | No fixed Debian package is available; application code does not directly call the affected C++ operation. Native dependency reachability remains unverified and is explicitly accepted residual risk. |
| Authoritative source | https://security-tracker.debian.org/tracker/CVE-2026-102010 |

Approval authorizes adding this exact match to
`infra/llmsecops/ecr-scan-exceptions.json`, validating the gate, committing and
pushing the decision, and retrying release. It does not authorize raising the
HIGH threshold or accepting other packages, versions, repositories or findings.
Any other backend/frontend finding requires its own evidence and decision.
Before expiry, recheck the Debian fix status and investigate native dependencies;
remove the exception when a patched release is available. An expired exception
does not match, so an unresolved HIGH finding will block release again.

### Retry result and approved additional repository scope

Commit `0bea979ea487012716ac042dec3a51307198730f` passed
[CI run 36804503356](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36804503356).
[Release run 36804828969](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36804828969)
accepted the AI exception with no unexcepted HIGH or CRITICAL findings. It then
stopped before deployment because the completed backend scan reported the same
HIGH `CVE-2026-102010` in `gcc-14 14.2.0-19`. The frontend gate was not reached.
A direct attempt to read its ECR scan failed because the local AWS session had
expired; no frontend scan result was established by this investigation.

**Additional scope approved 2026-10-01 by explicit repository-owner confirmation:**
The repository list now includes the backend and frontend. A frontend exception
matches only if the completed scan reports the identical CVE and package/version.

| Repository | Evidence and approved acceptance |
|---|---|
| `nus-iss-ais-team9-backend` | Confirmed identical CVE and source package/version in the retry; same expiry 2026-10-08 and explicitly accepted uncertainty about native dependency reachability. |
| `nus-iss-ais-team9-frontend` | Conditional acceptance of only this identical CVE and source package/version if its completed release scan reports it; same expiry 2026-10-08. Its native dependencies, including pandas, have not been assessed for reachability. The finding itself is not yet confirmed for this repository. |

All three images use the same pinned Debian base, but this is not proof of
identical findings or native dependency exposure. The owner separately approved
extending the repository list with these residual risks. Any other finding
or package/version remains blocked by the existing gate.

## 2026-09-30 Decision

**Status: approved 2026-09-30 by Tan Sean Leng** (drafted by Lee Jet Xuen).

Four exact-version exceptions are accepted for the synthetic-data demo: three new `openssl` findings (to 2026-10-14) and a renewed `zlib` finding (to 2026-10-30). The five 2026-08-31/2026-09-06 exceptions for `sqlite3`, `glibc` and `pcre2` are removed because none matched any finding in the last passing release. The zero-unexcepted-critical and zero-unexcepted-high release gates remain unchanged.

## 2026-09-30 Review

Release run `36661034068` for commit `8350652` passed CI but failed the Inspector/ECR gate on `nus-iss-ais-team9-ai` with three unexcepted HIGH findings. The previous release (`f821887`, run `36566489405`) shipped the same `openssl 3.5.7-1~deb13u2` and passed; the findings are new because OpenSSL published its advisory on 2026-09-29, not because a package changed. Pinning an older package would not help: `3.5.6-1~deb13u2` is also affected and predates Debian's security update.

| Finding | Package/version | OpenSSL severity | Affected feature | Exposure decision | Expiry |
|---|---|---|---|---|---|
| `CVE-2026-72897` | `openssl` `3.5.7-1~deb13u2` | Low | TLS server calling `SSL_set_SSL_CTX()` mid-handshake | Not reachable: no container terminates TLS | 2026-10-14 |
| `CVE-2026-84784` | `openssl` `3.5.7-1~deb13u2` | Low | QUIC connection-ID handling | Not reachable: no service uses QUIC or HTTP/3 | 2026-10-14 |
| `CVE-2026-84782` | `openssl` `3.5.7-1~deb13u2` | High | DTLS handshake retransmission | Not reachable: no service uses DTLS or UDP-based TLS | 2026-10-14 |
| `CVE-2026-85091` | `zlib` `1.3.dfsg+really1.3.1-1` | — | Non-blocking `gzwrite` with stale external buffers | Unchanged from 2026-09-06: not called | 2026-10-30 |

Reachability evidence, checked against this commit: all three Dockerfiles start plain-HTTP servers (`uvicorn` on 8001/8080 without TLS options, Streamlit on 8501); the ALB terminates HTTPS and forwards `Protocol: HTTP` to the target groups; no application code configures an in-process TLS server, QUIC, HTTP/3 or DTLS. The services use OpenSSL only as a TCP TLS client for OpenAI, AWS and Cognito calls, which none of the three OpenSSL findings affect. Debian lists all four exact Trixie packages as vulnerable with no fixed version; OpenSSL fixes the three openssl findings in 3.5.9. Sources: [OpenSSL advisory 2026-09-29](https://openssl-library.org/news/secadv/20260929.txt), [CVE-2026-72897](https://security-tracker.debian.org/tracker/CVE-2026-72897), [CVE-2026-84784](https://security-tracker.debian.org/tracker/CVE-2026-84784), [CVE-2026-84782](https://security-tracker.debian.org/tracker/CVE-2026-84782), [CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091).

Validation: `load_exceptions` accepts the file; replaying the blocked AI-image scan through `excepted_finding` leaves no blocking HIGH or CRITICAL finding; on 2026-10-15 the openssl exceptions lapse automatically. The backend and frontend images were not scanned in the failed run because the gate stopped at the AI image; they share the pinned base image and installed the same `openssl` version in the previous release, but any additional finding there will still block and needs its own review.

The earlier review below is retained as history.

The official `python:3.12-slim-trixie` tag still resolves to the already pinned multi-platform digest `sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217`. All three Dockerfiles pin that digest and run `apt-get upgrade` during the build. A package or base-image version change will not match these exceptions and must pass the normal scan gate or receive a separately reviewed exact-version exception.

## 2026-08-31 Evidence

Amazon Inspector/ECR reported `COMPLETE` scans for the images then deployed by ECS:

| Service | Immutable image tag | Findings accepted by exact match |
|---|---|---|
| AI service | `2cc386ec4ac724876fa92e226237a969a2ce8db7` | 1 critical, 3 high |
| Backend | `25a184b8c14618ec47452e78432db9e87fd38148` | 1 critical, 3 high |
| Frontend | `25a184b8c14618ec47452e78432db9e87fd38148` | 1 critical, 3 high |

Every accepted finding matched one of these exact source-package versions, with no unexcepted critical or high finding:

| Finding | Package/version | Upstream status | Exposure decision |
|---|---|---|---|
| `CVE-2026-11822` | `sqlite3` `3.46.1-7+deb13u1` | Trixie vulnerable; no stable fix; minor/no-DSA | Runtime services use PostgreSQL and do not accept hostile SQLite databases, arbitrary SQL, or FTS5 queries. |
| `CVE-2026-11824` | `sqlite3` `3.46.1-7+deb13u1` | Trixie vulnerable; no stable fix; minor/no-DSA | Same constrained FTS5 exposure as `CVE-2026-11822`. |
| `CVE-2026-5928` | `glibc` `2.41-12+deb13u3` | Trixie vulnerable; no stable fix; minor/no-DSA | Services use standard Unicode encodings and do not expose `ungetwc` over attacker-selected overlapping encodings. |
| `CVE-2026-5450` | `glibc` `2.41-12+deb13u3` | Trixie vulnerable; no stable fix; minor/no-DSA | Services do not invoke `scanf %mc` with attacker-controlled width values. |

The SQLite project states that these two findings require crafted FTS5 data and arbitrary SQL or a hostile database. The Debian tracker records the stable-package status and no-DSA classification for all four findings. Review the authoritative records directly: [SQLite vulnerability conditions](https://www.sqlite.org/cves.html), [CVE-2026-11822](https://security-tracker.debian.org/tracker/CVE-2026-11822), [CVE-2026-11824](https://security-tracker.debian.org/tracker/CVE-2026-11824), [CVE-2026-5928](https://security-tracker.debian.org/tracker/CVE-2026-5928), and [CVE-2026-5450](https://security-tracker.debian.org/tracker/CVE-2026-5450).

## Renewal Validation

Commit `e68333a75e89d3236c6b5215f2b75d0859d2e0f5` passed [CI and LLMSecOps run 33367930852](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33367930852), including all service tests, the policy evaluation, 79 infrastructure-script tests, SAST, integration/load smoke, and all three hardened container builds.

[Release run 33368100527](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33368100527) rebuilt and pushed all three immutable images, passed the exact-version Inspector/ECR gate, verified migrations, deployed the images, and passed the health and AI-safety smoke suite. ECS then reported all three services at steady state on that commit: AI task revision 37, backend revision 71, and frontend revision 44.

## Enforcement And Next Review

`infra/scripts/ecr_scan_gate.py` requires an exception to identify the exact CVE, source package, package version, and repository. It also requires a review date, reviewer, rationale, authoritative source, and expiry no more than 30 days after review. Expired exceptions are ignored, so a still-present critical or high finding blocks release automatically.

Recheck Debian stable status for `openssl` by 2026-10-14 and for `zlib` by 2026-10-30, and recheck the official Python base-image digest at each review. Remove an exception as soon as a fixed Trixie package is available. If no stable fix exists, a new review must repeat the live deployed-image scan, reconfirm reachability assumptions, and use a new maximum-30-day expiry.
