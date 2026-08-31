# Container Security Exception Review

## Current Decision

The four exact-version ECR scan exceptions remain temporarily accepted for the synthetic-data demo through 2026-09-30. This is a 30-day renewal from the 2026-08-31 review, not a permanent suppression. The zero-unexcepted-critical and zero-unexcepted-high release gates remain unchanged.

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

## Enforcement And Next Review

`infra/scripts/ecr_scan_gate.py` requires an exception to identify the exact CVE, source package, package version, and repository. It also requires a review date, reviewer, rationale, authoritative source, and expiry no more than 30 days after review. Expired exceptions are ignored, so a still-present critical or high finding blocks release automatically.

Recheck Debian stable status and the official Python base-image digest by 2026-09-30. Remove an exception as soon as a fixed Trixie package is available. If no stable fix exists, a new review must repeat the live deployed-image scan, reconfirm reachability assumptions, and use a new maximum-30-day expiry.
