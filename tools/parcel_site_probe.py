from __future__ import annotations

import re
import urllib.request


URL = "https://www3.newcastlede.gov/parcel/search/"


def main() -> None:
    html = urllib.request.urlopen(URL, timeout=30).read().decode("utf-8", "ignore")
    for match in re.finditer(r"<input[^>]+>", html):
        tag = match.group(0)
        if any(text in tag for text in ("Parcel", "TextBox", "Button", "Radio", "Search")):
            print(tag[:500])
    print("\nLinks:")
    for link in re.findall(r'href="([^"]+)"', html)[:80]:
        print(link)


if __name__ == "__main__":
    main()
