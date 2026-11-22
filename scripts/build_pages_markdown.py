#!/usr/bin/env python3
"""Generate the public Markdown companions from the three Pages documents."""

import argparse
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin


DOCS = Path(__file__).resolve().parents[1] / "docs"
BASE = "https://itsdavis.com/DOPPLERGEIST/"
PAGES = {
    "index": "",
    "examples": "examples.html",
    "how-it-works": "how-it-works.html",
}


def pandoc(content, source, target):
    return subprocess.run(
        ["pandoc", "--from", source, "--to", target, "--wrap=none", "--markdown-headings=atx"],
        input=content, text=True, check=True, capture_output=True,
    ).stdout


def resolve_links(nodes, url):
    for node in nodes:
        if isinstance(node, dict):
            if node.get("t") in {"Link", "Image"}:
                target = node["c"][2]
                target[0] = urljoin(url, target[0])
            resolve_links(node.values(), url)
        elif isinstance(node, list):
            resolve_links(node, url)


def render(name, route):
    url = BASE + route
    html = (DOCS / f"{name}.html").read_text(encoding="utf-8")
    main = re.search(r"<main\b[^>]*>(.*?)</main>", html, re.DOTALL)
    if not main or f'rel="canonical" href="{url}"' not in html:
        raise ValueError(f"Missing main content or canonical URL for {name}")
    article = re.sub(r"<svg\b[^>]*?/\s*>", "", main[1])
    article = re.sub(r"<(svg|button|noscript)\b[^>]*>.*?</\1\s*>", "", article, flags=re.DOTALL)
    article = re.sub(r"<br\s*/?>", " ", article)
    document = json.loads(pandoc(article, "html", "json"))
    resolve_links(document["blocks"], url)
    markdown = pandoc(json.dumps(document), "json", "gfm-raw_html").strip()
    if not markdown.startswith("# "):
        raise ValueError(f"Markdown heading missing for {name}")
    heading, rest = markdown.split("\n\n", 1)
    return f"{heading}\n\n[Canonical page]({url})\n\n{rest}\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check that published Markdown is current")
    check = parser.parse_args().check
    for name, route in PAGES.items():
        article = render(name, route)
        output = DOCS / f"{name}.md"
        if check:
            if not output.exists() or output.read_text(encoding="utf-8") != article:
                raise SystemExit(f"Regenerate {output.name} with {Path(__file__).name}")
        else:
            output.write_text(article, encoding="utf-8")


if __name__ == "__main__":
    main()
