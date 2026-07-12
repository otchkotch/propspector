from __future__ import annotations

import argparse
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe candidate public code-source URLs.")
    parser.add_argument("urls", nargs="+")
    args = parser.parse_args()
    for url in args.urls:
        print("---", url)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read().decode("utf-8", "ignore")
            print("status", getattr(response, "status", "?"), "chars", len(data))
            print(data[:1200])
        except Exception as exc:
            print(type(exc).__name__, exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
