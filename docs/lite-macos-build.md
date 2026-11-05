# macOS Lite build

This fork is based on Brave 1.98.63 and Chromium 156.0.8078.80. On macOS,
Wallet, Rewards, VPN and Leo AI default to disabled at compile time.

Chromium's Autofill, password manager and translation are shared components.
Small Chromium patches disable their main filling and translation paths on
macOS. The main menu entries and password manager WebUI are removed. Their code,
some settings routes and resources may still be present in the binary. Existing
saved data is not deleted. Browser tests cover the altered menu and feature
gates; a successful build and test run are required to validate them.

Manually starting `Brave Lite macOS staged build` launches five macOS 26 runners to compile V8,
Blink core, Blink modules, content, and browser targets. The targets share
dependencies, so some work is duplicated. Each runner saves its own eligible
C/C++ compiler results in up to four artifacts, saving newly cached files at
roughly 2 GiB intervals or before each time deadline. Each shard stops at about
8 GiB; the five shards can occupy around 40 GiB in total. The main build checks
and reads the available parts of one shard at a time,
limiting disk use; its cache statistics show how much work was reused. Other
build actions and final linking run separately.

Clang modules and precompiled headers are disabled to make more compiler
outputs eligible for ccache. This can make an initial compile slower; cache
hit rate and total time must be measured on the real build.

The main build uses at most eight successive stages. By default it starts with
the `chrome/browser` target and its cache, then builds and links the browser.
The generated build graph for this configuration shows that this target's
commands include those of the other four shard targets. `start_phase` can be
set to 1–4 to start with an earlier target when needed. An interrupted phase
continues in the next stage. Each stage saves its checkout and build output in up to sixteen 4 GiB
compressed, SHA-256-verified volumes; the next stage restores those volumes.
The full checkout is preserved so that incremental build metadata and source
timestamps survive. Later stages reuse the already checked GN graph unless its
arguments change or graph generation was interrupted. A shortage of disk space
stops the workflow for inspection. Restore streams each volume from GitHub,
checking its SHA-256 while extracting, so an extra complete local copy of the
compressed checkpoint is not required. Each stage also uploads newly compiled
C/C++ cache entries in up to four parts at about 2 GiB intervals or before
successive time deadlines, up to about 8 GiB total. An upload failure causes
the next part to retry the unsaved entries. Earlier uploaded parts survive an
interrupted stage or failed full checkpoint.
Artifacts are retained for up to 90 days. Actual build speed, artifact sizes and
GitHub storage availability need to be measured on a full build.

To resume manually, run the workflow on the same commit and enter the previous
run ID, stage number, and attempt. If the checkpoint was created by a resumed
run, enter the original shard run ID and attempt as well. Restore requires the
same source commit, workspace path, architecture, macOS major version, Xcode
build and SDK version. If the workflow changed after the checkpoint was saved,
enter the checkpoint's source commit in `resume_source_commit`. The app artifact
records both the source and workflow commits. The runner image and macOS minor
version may differ. Checkpoints include executable build outputs; the smoke test
still needs to pass after a restore.

The `rescue_cache` input can add another cache to the selected shard cache.
Use `RUN_ID:SHARD:ATTEMPT` for an earlier parallel shard, or
`RUN_ID:STAGE:SHARD:ATTEMPT` for a stage cache. The run log and artifact name
contain these numbers. This also allows an earlier checkpoint to benefit from
a later stage cache when the later checkpoint is unavailable. A cache contains
eligible compiler results, so other build work may need to run again.

For a new build, supplying an earlier shard run ID skips the five shard jobs
and attempts to reuse the available caches, including caches saved after a
failed compiler job. Missing shards do not prevent the later stages from
running. Ccache checks compiler content, command arguments and inputs when
deciding whether to reuse an object; changes may reduce the cache hit rate.
Alternatively, supplying a seed run ID starts five new shard jobs and seeds
each one from its corresponding earlier single-cache artifact, up to 1 GiB per
shard. Missing, invalid or larger seed artifacts are skipped.

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
For a stage cache, put its downloaded parts under a separate root and rename
each directory to `brave-lite-shard-SHARD-part-PART-aATTEMPT` before using the
same verification command with the shard and attempt from its artifact names.

For a complete checkpoint, download its manifest and every volume listed in the
manifest into one directory. On an Apple Silicon Mac with the same macOS major
version, Xcode build and macOS SDK, an empty workspace can be restored with
`zstd` installed:

```sh
python3 /path/to/current/brave-core/build/ci/lite_checkpoint.py restore --portable \
  --workspace /path/to/empty/workspace --checkpoint /path/to/checkpoint \
  --repository GuangDai/brave-core --commit SOURCE_COMMIT_FROM_MANIFEST
```

The default requires the original workspace path. Add `--allow-relocation` to
restore elsewhere and regenerate GN before building: leave
`BRAVE_LITE_REUSE_GN` unset. Relocation has passed a small fixture test; reuse
of a complete Chromium build at a new path has yet to be validated. Keep the
separate compiler-cache artifacts as well.

On success, the workflow verifies the compiled feature flags, runs a headless
browser smoke test, and uploads an unsigned Apple Silicon app ZIP and SHA-256
checksum. It then attempts to save the final build checkpoint as well, so a
later test build can reuse the output. The app is not notarized. The source
browser tests still require a separate successful test build and run.
