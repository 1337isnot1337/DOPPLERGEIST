"""Derive GHCR metadata and publication eligibility from a GitHub event.

This helper never authenticates or publishes. The workflow also guards its
package-write job independently, before granting that job a token.
"""
import json
import os
from pathlib import Path
import re
import subprocess


REPOSITORY = "1337isnot1337/DOPPLERGEIST"
_VERSION = re.compile(
    r"refs/tags/(v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?)"
)


def metadata(repository, event, ref, revision):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository name")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Image revision must be a complete Git commit ID")
    matched = _VERSION.fullmatch(ref)
    version = matched.group(1) if matched else None
    if version and (len(version) > 128 or any(
            part.isdecimal() and len(part) > 1 and part.startswith("0")
            for part in (matched.group(2) or "").split("."))):
        version = None
    main = ref == "refs/heads/main"
    publish = repository == REPOSITORY and (
        event == "push" and (main or version is not None)
        or event == "workflow_dispatch" and main
    )
    image = "ghcr.io/" + repository.lower()
    version = "main" if main else version or "sha-" + revision
    tags = [f"{image}:sha-{revision}", f"{image}:{version}"] if publish else []
    return {"publish": publish, "image": image, "revision": revision,
            "version": version, "tags": tags}


def main():
    revision = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
    values = metadata(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_EVENT_NAME"],
                      os.environ["GITHUB_REF"], revision)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        for key, value in values.items():
            if isinstance(value, (bool, list)):
                value = json.dumps(value, separators=(",", ":"))
            output.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
