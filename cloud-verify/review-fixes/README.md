# Review-fixes cloud verification

Run from the cloud VM, with Docker running, Git, Python 3, curl, and
`$HTTPS_PROXY` configured. The checkout must be clean and contain the
committed review-fixes tests and this directory. The runner never mounts a
Docker socket into a container and never uses real upload data.

Run one command from any directory:

```bash
bash /path/to/checkout/cloud-verify/review-fixes/run.sh /path/to/checkout A
```

Use `B` for the fixed-code batch, or `final` for final acceptance.
The program snapshots the checkout with `git archive HEAD`, reconstructs
GitHub Composer dist ZIP cache entries from locked Git source references,
installs development dependencies in a disposable Composer container, builds
the Chiseled candidate from `Dockerfile.chiseled`, and builds the test
image from its immutable image ID. It checks PHP version, module list and PHP
binary hash before running. A per-run private network and MySQL 8.4 fixture,
synthetic credentials, isolated volumes and temporary diagnostics are removed
when the run finishes. No host-wide Docker cleanup or prune is performed.
The runner's MySQL data directory uses tmpfs, so its data is held in memory and discarded when the container stops.

The runner executes the selected regressions and the full LDAP,
S3Compatibility and LDAP wizard test files with JUnit, then exercises the
synthetic staging marker against the Chiseled candidate, regular Docker image
and a direct preparation-stage fixture. It launches real Chiseled Apache
instances for valid, empty, unset, and invalid forwarded-header cases. In round
A it also removes the safety-backup option in a separate temporary snapshot,
builds a separate image, and records the endpoint test's mutation result. The
actual checkout and production Dockerfiles are never modified by the runner.

After the LDAP/S3/wizard runs, rounds other than A also run `shellless_order`
in one PHPUnit process: `ShelllessSchedulerTest.php`, `ShelllessOptInTest.php`,
then `RestoreToRemoteDiskTest.php`. Locked PHPUnit 11.5.55 accepts multiple
file arguments in order; `--order-by default,no-depends` prevents reordering.
The run uses the project's `phpunit.xml` (bootstrap and PHP/env settings,
`processIsolation="false"`, no random execution order). Every test must pass;
JUnit errors, failures and skips are errors, as for the other required runs.

At startup the runner removes resources carrying the review-fixes.run label
from interrupted runs. Do not run two instances concurrently: they share that
label. Git mirrors persist under ~/.cache/review-fixes/mirrors; set
REVIEW_FIXES_CACHE_DIR to change the parent cache directory. The optional
REVIEW_PROXY_CA points to the proxy CA; otherwise
/root/.ccr/agent-proxy-ca.crt is used when present. The CA is inserted only
into the temporary Chiseled build tools stage and the candidate is checked for
its absence. The runner substitutes the regular Dockerfile network fetches
only in its temporary context.

The results include a per-test round-A expectation (red, control, or existing)
and whether the observed result and failure reason matched. All JUnit errors,
PHPUnit exit 2, skips, unexpected existing/control failures, and missing or
wrong-reason RED results are errors. The FR-9 unmutated test must pass before
the mutated test is accepted. A separate, redacted runner-debug-<round>.log
under the review-fixes cache directory records command output; review it before sharing. Skipped-test summaries are
included in the JSON.

Each run records `python3 -I docker/chiseled/repin_app_inputs.py --check` on the
cloud host before building and stops on lock drift. Round B and final require
all unmutated tests and probes to pass with no skips; the FR-9 mutation must
still fail for its specific assertion.
The startup Go regression is compiled with the candidate's pinned Go builder;
the resulting static test executable runs inside the candidate-derived image.
Before the candidate build in every round (including A), the `go_checks` probe
runs `gofmt -l .` (requiring no listed files), `go vet ./...`, then `go test ./...`
in the same pinned Go image with networking disabled and the source mounted
read-only. It uses `CGO_ENABLED=0`, matching FR-8, and records `passed` and
`exit_code`; any failure stops the run.

The results file is
`cloud-verify/review-fixes/results-<round>.json`: image identities,
runtime comparison, per-test status and first-line failure messages, counts,
skips, probe outcomes, and setup errors. A failed assertion is recorded as a
test or probe result; a setup failure is recorded under `errors` and makes
the runner exit non-zero. JUnit errors in `errors` are grouped by run label and
redacted message, with a count and the first affected test as an example.
Failed commands include the first matching error line from redacted output,
preferring a compiler error over a generic BuildKit `failed to solve` wrapper.
Go check failures use the same cause selection, or `see debug log` if none matches.
Messages are truncated to 300 characters; empty messages appear as `(no message)`.
When any tests error, the first entry summarizes the total and most common cause.
Per-test details remain in `tests`. If the unmodified FR-9 test did not pass,
missing mutation results are reported as skipped because the baseline did not pass.
Round A contains expected failures: examine the
individual outcomes and causes instead of treating a zero runner exit as
feature success. Report missing JUnit, skips, setup errors, and unexpected
failures to the orchestrator; do not change runtime extensions or use a
different PHP image as a fallback.

The build helper needs access to Git source repositories even though GitHub
dist ZIP endpoints return 403. If Docker Hub rate-limits, authenticate or retry
in the cloud environment. A strict overlay check rejects a differing production
package file, including differences other than the repository's already
applied database-dumper patch. Such a failure is an environment or dependency
finding to report, not permission to overwrite production files.
