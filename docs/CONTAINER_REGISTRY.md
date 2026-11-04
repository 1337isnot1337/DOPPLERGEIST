# Published container images

The publishing workflow targets:

```text
ghcr.io/1337isnot1337/dopplergeist
```

It builds the existing Dockerfile for `linux/amd64`. The runtime, non-root user,
default command, license, and persistent-volume paths match the
[Docker setup](DOCKER.md). ARM images are not published by this workflow.

After the package is published and made public, pull and start it with:

```bash
docker pull ghcr.io/1337isnot1337/dopplergeist:main
docker run --detach --init --name dopplergeist \
  --publish 127.0.0.1:8765:8765 \
  --mount type=volume,src=dopplergeist-jobs,dst=/data/jobs \
  --mount type=volume,src=dopplergeist-cache,dst=/home/dopplergeist/.cache/dopplergeist \
  ghcr.io/1337isnot1337/dopplergeist:main
```

Open `http://127.0.0.1:8765`. Online data acquisition remains disabled by default.
See the Docker setup for data configuration, restart behavior, and alternate
ports. Publication does not supply flight archives, recordings, terrain, or a
scientific validation result.

## Publication and tags

The **Publish container to GHCR** workflow runs after pushes to `main`. A
maintainer can also run it from the Actions page with `main` selected. Other
branches, forks, pull requests, and research/data release events do not publish.
The checkout is pinned to the triggering commit.

| Reference | Meaning |
| --- | --- |
| `:main` | A checked build whose source was still the current `main` head immediately before publication. |
| `:sha-<full-commit-sha>` | A checked build of that source commit. |
| `@sha256:<registry-digest>` | The exact published image content recorded in the workflow summary. |

An older rerun still publishes its commit tag, but cannot move `main` back when
the branch has already advanced. Builds are serialized with pending runs queued;
the queue does not promise source-commit order. A branch can also advance during
a push, so `main` is a publication reference, not a live branch-head guarantee.
There is no `latest` or release-version tag. Existing release bundles contain
research evidence and must not be represented as software images.

Both named tags are mutable. Rebuilding the same commit can pick up changed base
images or package dependencies. For a fixed deployment, replace `:main` with the
complete digest reference shown in the successful workflow summary.

The publication job builds and loads one image, checks that image, then pushes
the same local image. Checks cover CLI startup, dependency consistency, FFmpeg,
native imports, the non-root user, browser assets, and installed license files.
The separate Docker CI workflow also checks HTTP access and persistent volumes.
Neither workflow generates audio, tracks, or scientific results.

## Package access and first publication

GitHub documents that a newly published container package defaults to private,
even when its source repository is public. A successful push establishes
authenticated publication; it does not establish anonymous download access.
See [GitHub's Container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

After the first successful run, the package owner must inspect the
[`dopplergeist` package](https://github.com/users/1337isnot1337/packages/container/package/dopplergeist)
and its settings. If public distribution is intended, set package visibility to
public and verify an anonymous pull of the published digest. Repository access
inheritance does not itself make the package public. See
[package visibility and access](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).

The job uses the repository's `GITHUB_TOKEN` with only `contents: read` and
`packages: write`. The source label links the image to this repository. No
personal access token is required. If an existing same-name package was created
without a repository link, its owner may need to connect it and grant this
repository Actions access before publication succeeds.

The image retains `PolyForm-Noncommercial-1.0.0` and the bundled MIT legacy notice.
Registry availability does not change those license terms or third-party rights.

## Verification after merge

Check the actual **Publish container to GHCR** run for the merged commit. Confirm
the runtime checks and pushes passed, then copy the digest from its summary.
Inspect the manifest and pull that digest from a client that has no GHCR login.
The anonymous pull is the public-availability check. A logged-in workflow's
registry access cannot replace it.

Inspect the downloaded image's source and revision labels:

```bash
docker image inspect \
  --format '{{index .Config.Labels "org.opencontainers.image.source"}} {{index .Config.Labels "org.opencontainers.image.revision"}}' \
  ghcr.io/1337isnot1337/dopplergeist@sha256:REPLACE_WITH_PUBLISHED_DIGEST
```

The source must be `https://github.com/1337isnot1337/DOPPLERGEIST`. The revision
must match the workflow's triggering commit, including the merged commit for
the first post-merge publication.

To check the downloaded image's CLI without starting a scientific job:

```bash
docker run --rm ghcr.io/1337isnot1337/dopplergeist@sha256:REPLACE_WITH_PUBLISHED_DIGEST --help
```

The workflow uses commit-pinned releases of the official
[Docker actions](https://docs.docker.com/build/ci/github-actions/).
Its serialized queue follows GitHub's
[concurrency rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
