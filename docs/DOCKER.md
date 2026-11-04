# Run with Docker

Build from the repository checkout:

```bash
docker build --tag dopplergeist:local .
```

The multi-stage image builds the four native extensions with GCC. The runtime
contains Python 3.12, FFmpeg, the installed Python dependencies and browser assets.
It runs as UID/GID `10001`, with the repository license and bundled notices
preserved in the installed package. Recordings, jobs, caches and historical
evidence are excluded from the build context.

## Start the application

```bash
docker run --detach --init --name dopplergeist \
  --publish 127.0.0.1:8765:8765 \
  --mount type=volume,src=dopplergeist-jobs,dst=/data/jobs \
  --mount type=volume,src=dopplergeist-cache,dst=/home/dopplergeist/.cache/dopplergeist \
  dopplergeist:local
```

Open `http://127.0.0.1:8765`. Docker creates the named volumes when needed.
The jobs volume preserves uploads, results and checkpoints. The cache volume
preserves downloaded flight archives, indexes, terrain and geoid data.
Existing bind-mount directories must be writable by UID/GID `10001`.

The default command is:

```bash
dopplergeist serve --host 0.0.0.0 --port 8765 --jobs /data/jobs
```

The service listens on the container's interfaces; the published host port stays
on loopback. Host networking is unnecessary. The unauthenticated local service's
Host and Origin checks remain enabled. Use the loopback publication shown above.
Normal non-container `serve` still defaults to `127.0.0.1`.

## Enable data downloads or use existing data

The default container has online acquisition disabled. Audio intake and discovery
remain available; historical search needs configured data and a defensible
recording-start window. To permit public downloads, append the following command
after `dopplergeist:local` in the `docker run` command above:

```bash
serve --host 0.0.0.0 --port 8765 --jobs /data/jobs --online --max-runtime 14400
```

Downloads can require hours and tens of gigabytes. The default upload limit is
100 MiB; add `--max-upload-mb 250`, for example, when a larger recording is needed.
The [local workflow](PRODUCT.md) explains timing evidence and search limits.

For an offline provider configuration, mount the JSON file read-only and append
`--config /config/operator.json` to the complete `serve` command. For example,
add this mount to `docker run`:

```bash
--mount type=bind,src=/absolute/path/operator.json,dst=/config/operator.json,readonly
```

Configuration paths must refer to paths inside the container. Mount any existing
indexes and terrain at those paths. If the configuration changes `cache_root`,
mount a persistent writable volume at that location as well.

## Stop, restart and change ports

```bash
docker stop --time 30 dopplergeist
docker start dopplergeist
```

The image uses SIGINT for normal shutdown so the service closes its job manager
and stops workers. Completed jobs remain readable after restart. Resume a stopped
job explicitly through the UI when its checkpoint is compatible. Named volumes
survive container removal; reuse the same volume names when replacing the image.
The [backup procedure](PRODUCT.md) requires a stopped, consistent job directory.

Keep host and container port numbers equal because the local Host check uses the
service port. For port `8876`, use `--publish 127.0.0.1:8876:8876` and append the
complete command `serve --host 0.0.0.0 --port 8876 --jobs /data/jobs` to the image
name. A mapping such as `8876:8765` will not pass the existing Host check.

## Verification

The Docker workflow builds the image and checks native imports, FFmpeg, GIS/audio
libraries, packaged browser assets and licenses. It checks actual HTTP access
through a bridge-published loopback port, the existing Host/Origin checks, clean
shutdown, and non-root writes that persist across containers in both volumes.
These checks generate no audio, flight tracks or scientific job results.
