# Experimental macOS browser feature tests

This workflow is an isolated prototype. It has not built or run the real
browser test binary. A successful application build and a complete checkpoint
must exist first. The previously uploaded application and its checkpoint are
never overwritten by this workflow.

`lite-browser-verification.yml` accepts the original source commit, checkpoint
run, stage and attempt. Use `brave-lite` for a completed application checkpoint
and `brave-lite-verify` for a checkpoint produced by this workflow. It restores
only a matching macOS architecture, Xcode/SDK and workspace, then builds
`brave_browser_tests` using the existing Static ARM64 GN flags. Compiler results
are saved in four incremental parts, with the same 2/4/6/8 GiB thresholds and
time/disk protection as the application workflow. A complete isolated workspace
checkpoint is attempted after compilation stops or fails. Rerun the workflow
manually with the verification run ID, stage `1`, attempt, original source and
matching overlay setting to continue from such a checkpoint. On a verification
checkpoint resume, the workflow can also read that run's verified test cache;
an explicit earlier verification cache run and attempt may be supplied. The
optional cache is skipped if its provenance, contents, available disk or
remaining time fail validation.

The test launcher is first asked to list every expected test. The run is only
accepted when each exact test appears once in the single-iteration Chromium
summary with status `SUCCESS`; empty, missing, skipped, retried, timed-out or
failed tests are failures. Logs, explicit outcomes, provenance and their file
checksums are uploaded independently. The application executable's SHA-256 is
checked before and after building tests. This verifies the executable only;
the original app artifact remains the reference for the complete package.

The optional test overlay applies only to the pinned application source listed
in `lite_browser_checkpoint.py`. Its patch and the original and patched test
source blobs are checked before use. The overlay is applied only in the
disposable restored test workspace, and its provenance is saved with the test
results and verification checkpoint. It changes test code, so the test binary
is not byte-identical to the released app.

All test artifacts use `brave-lite-verify-*` or
`brave-lite-browser-test-results-*` names. They are intentionally distinct from
production app checkpoints and caches. `build/ci/lite_browser_backup_verify.py`
provides independent, read-only verification of artifact directories; it is not
an automatic downloader. Its `--help` lists the required repository,
source, workflow commit, application SHA-256, overlay setting and checkpoint
attempt. Obtain the expected application SHA-256 from the original authenticated
application or checkpoint, and the expected workflow commit from the artifact's
own run. Do not use the artifact's self-reported values as the trust source.
The helper verifies each checkpoint volume against its manifest, and the full
checkpoint command requires every listed volume. Successful results require
provenance, controller and launcher logs, the exact test list and a passing
summary. A valid incomplete artifact is reported with its actual status, not as
a successful test. Checksums detect accidental corruption; their authenticity
depends on the trusted source of the expected values and artifact download.
The default test set checks Autofill and password filling enablement in ordinary
and private windows, password-store insertion and password-manager page
navigation, and the disabled translation preference. The optional overlay also
checks the manual translation path and strengthens the password-list check.
These tests do not exercise third-party extensions, Passkeys, actual form
filling, or existing saved-data migration. Browser test execution may also need
a working macOS graphical session; real CI behavior and Chromium-scale
disk/time costs remain unverified. GitHub artifact retention limits apply.
