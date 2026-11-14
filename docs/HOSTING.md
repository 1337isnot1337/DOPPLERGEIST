# Password-protected hosting

The loopback service remains password-free by default. To serve it through a
trusted HTTPS reverse proxy, set these runtime environment variables before
starting `dopplergeist serve --host 0.0.0.0`:

| Variable | Value |
| --- | --- |
| `DOPPLERGEIST_PUBLIC_ORIGIN` | Exact HTTPS origin, such as `https://your-app.fly.dev`, without a trailing slash or path |
| `DOPPLERGEIST_AUTH_PASSWORD` | Nonempty private password supplied as a runtime secret |
| `DOPPLERGEIST_AUTH_USER` | Optional username; defaults to `dopplergeist` |

Setting any of these variables enables configuration validation. Missing or
invalid settings stop startup before a listener opens. HTTP Basic authentication
protects the UI, assets, job API, uploads and artifacts. Browsers prompt for the
credentials. Authenticated requests must still use the configured Host and
matching Origin; non-browser clients may omit Origin. Forwarded host headers do
not override that fixed origin. The reverse proxy must terminate HTTPS and keep
the application port private: the Python listener itself speaks HTTP. One shared
credential grants access to every job in this store; there are no per-user stores.

## Fly.io

The repository's `fly.toml` is an example for one machine and one persistent
50 GB volume. It uses the explicit `fly` Docker build target; ordinary Docker
builds retain their existing non-root local startup. The Fly entrypoint prepares
the mounted directories, then drops to UID/GID 10001 before starting the service.
Jobs live in `/data/jobs`, and `--online` acquisition uses
`/data/.cache/dopplergeist`. Fly enforces HTTPS at its proxy. TCP health checks
avoid publishing an unauthenticated HTTP endpoint or storing credentials in a
health-check definition. Autostop is disabled so a background analysis continues
when the browser is closed. See the [Fly configuration reference](https://docs.fly.io/reference/configuration).

For a new deployment with the Fly CLI installed and authenticated:

1. Copy `fly.toml` to a private operator file, such as `fly.local.toml`, and replace
   the app name and `DOPPLERGEIST_PUBLIC_ORIGIN` with your own matching values.
2. Create the app with `fly apps create YOUR_APP` and an encrypted volume with
   `fly volumes create dopplergeist_data --app YOUR_APP --region iad --size 50`.
   These create billable resources; use an existing app/volume when appropriate.
3. Import `DOPPLERGEIST_AUTH_PASSWORD=YOUR_PRIVATE_PASSWORD` through
   `fly secrets import --app YOUR_APP`, using stdin from your password manager or
   another private source. Do not put the password in Git or command arguments.
4. From the repository root, run `fly config validate --config fly.local.toml`,
   then `fly deploy --config fly.local.toml --ha=false`. Keep exactly one machine
   attached to the store; a second machine has a different local volume.
5. Open the configured HTTPS URL and verify a missing/wrong password receives
   401, authenticated UI/API requests succeed, and an unrelated Origin receives
   403. Uploads still need a defensible recording time for historical search.

The initial 2 GB shared CPU machine is a deployment example, not validated search
capacity. Downloads can fill 50 GB, and long searches can exhaust memory or the
four-hour job limit. Adjust capacity from observed workload requirements. Stop
the service before a consistent backup, as described in [PRODUCT.md](PRODUCT.md).
Password changes take effect after the application restarts.

## Verification

`python -m pytest -q tests/test_hosted_service.py` exercises real HTTP requests,
including failed configuration, authentication on protected routes, Host/Origin
checks, local defaults and byte-preserving access to a saved real artifact. It
generates no audio, flight tracks or scientific results. Docker CI also starts
the Fly target against a fresh volume, checks non-root execution and persistent
writes, and confirms startup fails without authentication configuration.

This source integration does not redeploy the existing owner-operated app or
establish field localization accuracy.
