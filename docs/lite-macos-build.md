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
C/C++ compiler results in up to four artifacts, saving newly cached files at
roughly 2 GiB intervals or before each time deadline. Each shard stops at about
8 GiB; the five shards can occupy around 40 GiB in total. The main build checks
and reads the available parts of one shard at a time,
limiting disk use; its cache statistics show how much work was reused. Other
build actions and final linking run separately.

The main build uses at most eight successive stages. The first five try each
target and its corresponding cache; the remaining stages build and link the
browser. Each stage saves its checkout and build output in up to eight
compressed, SHA-256-verified volumes; the next stage restores those volumes.
The full checkout is preserved so that incremental build metadata and source
timestamps survive. A shortage of disk space stops the workflow for inspection.
Artifacts are retained for up to 90 days. Actual build speed, artifact sizes and
GitHub storage availability need to be measured on a full build.

To resume manually, run the workflow on the same commit and enter the previous
run ID, stage number, and attempt. If the checkpoint was created by a resumed
run, enter the original shard run ID and attempt as well. Restore requires the
same commit, workspace path, architecture, macOS major version, Xcode build and
SDK version. The runner image and macOS minor version may differ. Checkpoints
include executable build outputs; the smoke test still needs to pass after a
restore.

For a new build, supplying an earlier shard run ID skips the five shard jobs
and attempts to reuse the available caches, including caches saved after a
failed compiler job. Missing shards do not prevent the later stages from
running. Ccache checks compiler content, command arguments and inputs when
deciding whether to reuse an object; changes may reduce the cache hit rate.

If GitHub cannot finish the build, the cache artifacts can also be downloaded
for a compatible Apple Silicon Mac. Preserve the artifact directories and use
ccache 4.14.2 with `CCACHE_COMPILERCHECK=content` and `CCACHE_BASEDIR` set to
the parent of the `src` checkout. From the Brave Core checkout, verify one cache
and print the environment settings for it with:

```sh
python3 build/ci/lite_cache_parts.py verify --portable \
  --root /path/to/downloaded-artifacts --workspace /path/to/workspace \
  --repository GuangDai/brave-core --commit "$(git rev-parse HEAD)" \
  --attempt 1 --shard 1
```

The command prints the read-only `CCACHE_REMOTE_STORAGE` and
`CCACHE_REMOTE_ONLY` settings. Use the same `Static` build arguments and
`--gn=cc_wrapper:ccache` shown in the workflow. Different compiler, source,
SDK or paths can cause misses. Downloaded checkpoints and their source tree are
also available as a separate fallback; the automated restore applies the
stricter compatibility checks above.

On success, the workflow verifies the compiled feature flags, runs a headless
browser smoke test, and uploads an unsigned Apple Silicon app ZIP and SHA-256
checksum. The app is not notarized. The source browser tests still require a
separate successful test build and run.
