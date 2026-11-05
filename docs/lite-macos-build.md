# macOS Lite build

This fork is based on Brave 1.98.63 and Chromium 156.0.8078.80. On macOS,
Wallet, Rewards, VPN and Leo AI default to disabled at compile time.

Chromium's Autofill, password manager and translation are shared components.
Small Chromium patches disable their main filling and translation paths on
macOS. The main menu entries and password manager WebUI are removed. Their code,
some settings routes and resources may still be present in the binary. Existing
saved data is not deleted. Browser tests cover the altered menu and feature
gates; a successful build and test run are required to validate them.

The `Brave Lite macOS build` GitHub Actions workflow uses a macOS 26 runner,
initializes a shallow checkout and builds an unsigned Apple Silicon `Static`
browser. If it succeeds, the workflow uploads a ZIP and a SHA-256 checksum.
The build is not notarized.

The workflow restores a compiler cache after checkout and saves it even when
compilation fails or reaches its step time limit. This cache covers eligible
C/C++ compiler results, not the entire checkout, linker state, or every build
action. It is limited to 4 GB; GitHub's default 10 GB repository cache limit
and the runner's disk and time limits still apply. A cache hit can shorten a
later attempt, but completion across repeated hosted jobs is not guaranteed.
