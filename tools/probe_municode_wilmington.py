from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import http.cookiejar


MUNICODE_PAGE = "https://library.municode.com/de/wilmington/codes/code_of_ordinances?nodeId=PTIIWICO_CH48ZO"
MUNICODE_API_BASE = "https://library.municode.com/api"
COOKIE_JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with OPENER.open(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def fetch_api(path: str, params: dict[str, str]) -> dict:
    url = f"{MUNICODE_API_BASE}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": MUNICODE_PAGE,
            "Accept": "application/json, text/plain, */*",
        },
    )
    with OPENER.open(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    html = fetch_text(MUNICODE_PAGE)
    print("html length", len(html))
    print("cookies", [cookie.name for cookie in COOKIE_JAR])
    for params in (
        {"stateAbbr": "de", "clientName": "wilmington"},
        {"stateAbbr": "DE", "clientName": "wilmington"},
    ):
        try:
            print("client", params, fetch_api("Clients/name", params))
        except Exception as exc:
            print("client failed", params, exc)
    assets = re.findall(r'(?:src|href)="([^"]+)"', html)
    for asset in assets:
        print("asset", asset)

    scripts = [asset for asset in assets if asset.endswith(".js")]
    product_ids: set[str] = set()
    for script in scripts:
        url = urllib.parse.urljoin(MUNICODE_PAGE, script)
        try:
            text = fetch_text(url)
        except Exception as exc:
            print("script fetch failed", url, exc)
            continue
        if "wilmington" in text.lower() or "productId" in text:
            print("interesting script", url, len(text))
        product_ids.update(re.findall(r"productId['\"]?\s*[:=]\s*['\"]?(\d+)", text))
    print("product ids", sorted(product_ids))

    for candidate in sorted(product_ids):
        try:
            data = fetch_api("CodesContent", {"productId": candidate, "nodeId": "PTIIWICO_CH48ZO"})
        except Exception as exc:
            print("candidate failed", candidate, exc)
            continue
        print("candidate works", candidate, list(data))
        print(json.dumps(data, indent=2)[:2000])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
