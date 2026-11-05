# macOS Lite build

This fork is based on Brave 1.98.63 and Chromium 156.0.8078.80. On macOS,
Wallet, Rewards, VPN and Leo AI default to disabled at compile time.

Chromium's Autofill, password manager and translation are shared components.
Small Chromium patches disable their main filling and translation paths on
macOS. The main menu entries and password manager WebUI are removed. Their code,
some settings routes and resources may still be present in the binary. Existing
saved data is not deleted. Browser tests cover the altered menu and feature
gates; a successful build and test run are required to validate them.

`Brave Lite macOS staged build` starts five macOS 26 runners to compile V8,
Blink core, Blink modules, content, and browser targets. The targets share
dependencies, so some work is duplicated. Each runner saves its own eligible
C/C++ compiler results as an artifact when its target finishes, its time runs
out, or its cache reaches approximately 8 GiB. The five artifacts can occupy
around 40 GiB in total. The main build checks and reads one cache at a time,
limiting disk use; its cache statistics show how much work was reused. Other
build actions and final linking run separately.

The main build uses at most eight successive stages. The first five try each
target and its corresponding cache; the remaining stages build and link the
browser. Each stage saves its checkout and build output in up to eight
compressed, SHA-256-verified volumes; the next stage restores those volumes.
The full checkout is preserved so that incremental build metadata and source
timestamps survive. A shortage of disk space stops the workflow for inspection.
Artifacts expire after seven days. Actual build speed, artifact sizes and
GitHub storage availability need to be measured on a full build.

To resume manually, run the workflow on the same commit and enter the previous
run ID, stage number, and attempt. If the checkpoint was created by a resumed
run, enter the original shard run ID and attempt as well. Restore requires the
same workspace path and macOS runner image, Xcode, SDK and architecture used to
create the artifacts. A runner image update can therefore prevent a resume.

On success, the workflow verifies the compiled feature flags, runs a headless
browser smoke test, and uploads an unsigned Apple Silicon app ZIP and SHA-256
checksum. The app is not notarized. The source browser tests still require a
separate successful test build and run.
