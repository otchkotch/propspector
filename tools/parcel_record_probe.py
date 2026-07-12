from __future__ import annotations

from html.parser import HTMLParser
import re
import urllib.parse
import urllib.request


SEARCH_URL = "https://www3.newcastlede.gov/parcel/search/"


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._parts).split())
            self.links.append((text, self._href))
            self._href = None


def fetch(url: str, data: dict[str, str] | None = None) -> str:
    encoded = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=encoded)
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")


def hidden_fields(html: str) -> dict[str, str]:
    fields = {}
    for name, value in re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]+" value="([^"]*)"', html):
        fields[name] = value
    return fields


def search_parcel(parcel: str) -> str:
    html = fetch(SEARCH_URL)
    data = hidden_fields(html)
    data.update(
        {
            "ctl00$ctl00$ContentPlaceHolder1$ContentPlaceHolder1$_TextBoxParcelNumber": parcel,
            "ctl00$ctl00$ContentPlaceHolder1$ContentPlaceHolder1$_ButtonSearch": "Search",
        }
    )
    return fetch(SEARCH_URL, data)


def page_text(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.replace("&nbsp;", " ").split())


def main() -> None:
    import sys

    parcel = sys.argv[1] if len(sys.argv) > 1 else "0804930379"
    html = search_parcel(parcel)
    print(page_text(html)[:5000])
    parser = LinkParser()
    parser.feed(html)
    print("\nLINKS")
    for text, href in parser.links:
        if parcel in text or "detail" in href.lower() or "parcel" in href.lower():
            print(text, href)


if __name__ == "__main__":
    main()
