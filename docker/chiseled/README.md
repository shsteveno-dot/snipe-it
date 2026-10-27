# Chiseled runtime image

`Dockerfile.chiseled` builds a Snipe-IT image whose final stage is `scratch`. The runtime root is cut with
[Chisel](https://github.com/canonical/chisel) from Ubuntu 24.04 packages and contains no `/bin/sh`.

Build it from the repository root:

```bash
docker buildx build -f Dockerfile.chiseled --platform linux/amd64 -t snipeit-chiseled .
```

## What runs in the container

| Program | Source | Job |
|---|---|---|
| `snipeit-init` | `docker/snipeit-runtime/cmd/init` | first-run setup, permissions, migrations; hands the environment to the supervisor |
| `snipeit-supervisor` | `docker/snipeit-runtime/cmd/supervisor` | runs the web server, the queue worker and the scheduler |

Both are plain Go programs (no cgo) built in the first stage.

## Shell-less mode is opt-in

Without a shell, Laravel cannot start child processes through `sh -c`. The image sets
`SNIPEIT_SHELLLESS=true` (config key `app.shellless`). Only then:

* the scheduler runs Artisan commands from an argument array (`App\Console\Scheduling\*`), and
* `snipeit:restore` starts the database client from an argument array.

With the flag off (the default everywhere else) both use the framework's own behaviour, unchanged.

## Pinned inputs

Every input of the build is recorded by SHA-256 in `input-lock.<arch>.json`: the Ubuntu snapshot indexes and
packages, Chisel, the slice definitions (`slices/`), `composer.lock` and `docker/snipeit-runtime/go.mod`.
`fetch_inputs.py` downloads them and the build stops if any byte differs. The final root is cut without network
access (`build-cut.py` runs with `--network=none`).

`accepted-inputs.json` and `runtime_inputs_test.py` record the digests of the lock files themselves, so a lock
cannot change unnoticed.

### After changing composer.lock, go.mod or a slice

```bash
python3 docker/chiseled/repin_app_inputs.py          # rewrite the locks
python3 docker/chiseled/repin_app_inputs.py --check  # exit 1 if they are out of date
python3 docker/chiseled/runtime_inputs_test.py       # lock digests agree
```

### After changing the package set or snapshot date

Use `capture_snapshot.py` to record a new snapshot, review the package list in `package-review.json`, and verify
with `verify_snapshot.py`. That is a deliberate, reviewed change; `repin_app_inputs.py` never touches packages.

### Architectures

The amd64 image is built and tested. The arm64 lock is kept in step (its application inputs are re-pinned by the
same script) but the arm64 image has not been built or run.

## Tests

```bash
python3 -m unittest discover -s docker/chiseled -p '*_test.py'
( cd docker/snipeit-runtime && go vet ./... && go test ./... )
```
