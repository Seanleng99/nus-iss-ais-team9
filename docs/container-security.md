# Container Security Exception Review

## Current Decision

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
