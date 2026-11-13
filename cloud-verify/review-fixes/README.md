# Review-fixes cloud harness — incomplete

Do not run on the developer PC. This directory currently contains the test-image
scaffolding only. The cloud orchestration, Composer cache reconstruction, MySQL
fixture, Apache probe, staging-marker fixture, and consolidated results writer
are not implemented yet. Do not treat this directory as an executable round-A
procedure.

`Dockerfile.test` expects `CANDIDATE` to be the immutable local image ID for the
image built from `Dockerfile.chiseled` and `devvendor` to be a named BuildKit
context containing the matching locked Composer development vendor tree. Its
build-only overlay copies missing dev files and generated Composer autoload
metadata without copying production package files over the candidate. The final
stage retains the candidate PHP binary, extensions, and application layout.

Before using it, verify that the cloud-generated development tree matches the
repository lockfile and that the actual candidate runtime supports all required
PHPUnit dependencies. The overlay and image build have not been executed or
validated. Do not add extensions or substitute another PHP runtime if they fail.
Never mount a Docker socket into the test container.