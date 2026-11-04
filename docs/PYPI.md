# PyPI publication

The PyPI distribution name is `dopplergeist`. The Python package and console command are also named `dopplergeist`. The current distribution version is in `pyproject.toml`; the first planned PyPI release is **0.1.1** (Git tag `v0.1.1`). The existing `v0.1.0` GitHub release predates the PyPI workflow and does not trigger it retroactively.

## One-time setup

1. Sign in to [PyPI account publishing](https://pypi.org/manage/account/publishing/). Create a **pending GitHub trusted publisher** with these exact fields:
   - PyPI project: `dopplergeist`
   - GitHub owner: `1337isnot1337`
   - Repository: `DOPPLERGEIST`
   - Workflow filename: `python-package.yml`
   - GitHub environment: `pypi`
2. In the GitHub repository, open **Settings → Environments**. Create an environment named `pypi`. Restrict deployment to release tags (for example `v*`) and consider required reviewers. Only the publication job uses this environment or requests OIDC credentials.
3. From **Actions → Python distribution and PyPI → Run workflow** on `main`, verify that the smoke build, one source archive, and five-platform binary-wheel matrix all pass. Manual runs **do not upload to PyPI**.

PyPI pending publishers do not reserve the project name. The first successful upload creates the project. No API token or long-lived secret is required.

## Release

1. Land the intended code, tests, and version bump on `main`; update `pyproject.toml` to a version not previously uploaded to PyPI. This project's release workflow accepts only a GitHub release tag of the form `v<project.version>`.
2. In [GitHub Releases](https://github.com/1337isnot1337/DOPPLERGEIST/releases), create and publish a release tagged exactly `v0.1.1` (for the initial PyPI release). Point it to the tested commit. Do not republish or move an existing version tag.
3. The `Python distribution and PyPI` workflow runs the package smoke check, builds 20 platform-specific wheels (CPython 3.11–3.14 on Linux x86_64/aarch64, macOS x86_64/arm64 and Windows amd64), and builds one source archive. It validates names/version and publishes with `pypa/gh-action-pypi-publish` using GitHub OIDC only if all required jobs pass.
4. Verify the published distribution at [PyPI](https://pypi.org/project/dopplergeist/). In a fresh environment install with `pipx install dopplergeist` or `python -m pip install dopplergeist` and run `dopplergeist --help`.

Releases are immutable on PyPI: if an artifact was already uploaded, do not attempt to overwrite it. Bump the version and create a new tag instead. If publication failed *before* any files were uploaded, fix the cause and rerun the failed workflow; no new version is required.

## Packaging notes

- `ffmpeg` and `ffprobe` are executable system dependencies, not supplied by the PyPI wheel.
- Optional native C accelerators are built as platform/CPython-specific wheels. The source archive supports building from source where a compatible toolchain and required dependencies are available.
- The bundled web application assets and PolyForm Noncommercial/MIT-legacy notices must be included in the distributions.
- PyPI does not grant any additional rights to commercial use. See [commercial licensing](../COMMERCIAL-LICENSING.md).
