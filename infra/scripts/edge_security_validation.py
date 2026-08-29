import argparse
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def require_url(url: str, *, scheme: str | None = None) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("edge URL must use HTTP(S) and include a host")
    if scheme and parsed.scheme != scheme:
        raise ValueError(f"edge URL must use {scheme}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("edge URL must not contain credentials, query, or fragment")
    return parsed


def health_url(base_url: str) -> str:
    require_url(base_url, scheme="https")
    return f"{base_url.rstrip('/')}/_stcore/health"


def check_frontend_health(base_url: str, timeout_seconds: float = 15) -> None:
    request = urllib.request.Request(
        health_url(base_url), headers={"Accept": "text/plain"}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
        body = response.read(256).decode("utf-8", errors="replace")
        if response.status != 200 or body.strip().lower() != "ok":
            raise AssertionError(
                f"CloudFront health check failed with HTTP {response.status}"
            )


def check_direct_origin_denied(
    origin_url: str, timeout_seconds: float = 5
) -> str:
    parsed = require_url(origin_url)
    direct_health_url = urllib.parse.urlunparse(
        parsed._replace(path="/_stcore/health", params="", query="", fragment="")
    )
    request = urllib.request.Request(
        direct_health_url, headers={"Accept": "text/plain"}, method="GET"
    )
    try:
        with urllib.request.urlopen(  # nosec B310
            request, timeout=timeout_seconds
        ) as response:
            raise AssertionError(
                "direct origin bypass is reachable "
                f"(HTTP {response.status}); expected network denial or HTTP 403"
            )
    except urllib.error.HTTPError as error:
        if error.code != 403:
            raise AssertionError(
                f"direct origin returned HTTP {error.code}; expected HTTP 403"
            ) from error
        return "http_403"
    except (TimeoutError, urllib.error.URLError):
        return "network_denied"


def negotiated_tls_version(base_url: str, timeout_seconds: float = 10) -> str:
    parsed = require_url(base_url, scheme="https")
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection(
        (parsed.hostname, parsed.port or 443), timeout=timeout_seconds
    ) as connection, context.wrap_socket(
        connection, server_hostname=parsed.hostname
    ) as tls_connection:
        version = tls_connection.version()
    if version not in {"TLSv1.2", "TLSv1.3"}:
        raise AssertionError(f"unexpected negotiated TLS version: {version}")
    return version


def validate(
    frontend_url: str,
    origin_url: str,
    expected_custom_domain: str | None = None,
) -> dict[str, str | bool]:
    frontend = require_url(frontend_url, scheme="https")
    origin = require_url(origin_url)
    if expected_custom_domain and frontend.hostname != expected_custom_domain:
        raise AssertionError(
            f"frontend host {frontend.hostname} does not match {expected_custom_domain}"
        )
    check_frontend_health(frontend_url)
    denial = check_direct_origin_denied(origin_url)
    tls_version = negotiated_tls_version(frontend_url)
    return {
        "passed": True,
        "frontend_host": frontend.hostname or "",
        "origin_host": origin.hostname or "",
        "direct_origin_result": denial,
        "negotiated_tls_version": tls_version,
        "custom_domain_verified": bool(expected_custom_domain),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate CloudFront health, TLS, and direct-origin denial"
    )
    parser.add_argument("--frontend-url", required=True)
    parser.add_argument("--origin-url", required=True)
    parser.add_argument("--expected-custom-domain")
    parser.add_argument("--output")
    args = parser.parse_args()

    evidence = validate(
        args.frontend_url,
        args.origin_url,
        args.expected_custom_domain,
    )
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
