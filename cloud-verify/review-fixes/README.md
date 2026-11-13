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

The runner executes the selected regressions and the full LDAP,
S3Compatibility and LDAP wizard test files with JUnit, then exercises the
synthetic staging marker against the Chiseled candidate, regular Docker image
and a direct preparation-stage fixture. It launches real Chiseled Apache
instances for valid, empty, unset, and invalid forwarded-header cases. In round
A it also removes the safety-backup option in a separate temporary snapshot,
builds a separate image, and records the endpoint test's mutation result. The
actual checkout and production Dockerfiles are never modified by the runner.

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
records command output; review it before sharing. Skipped-test summaries are
included in the JSON.

The only persistent result is
`cloud-verify/review-fixes/results-<round>.json`: image identities,
runtime comparison, per-test status and first-line failure messages, counts,
skips, probe outcomes, and setup errors. A failed assertion is recorded as a
test or probe result; a setup failure is recorded under `errors` and makes
the runner exit non-zero. Round A contains expected failures: examine the
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