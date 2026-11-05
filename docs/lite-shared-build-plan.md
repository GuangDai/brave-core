# Experimental shared build plan

`lite_shared_plan.py` inspects a generated Ninja graph without compiling. It
partitions browser object targets into five groups, finds object outputs shared
by multiple groups, and writes a Ninja target for those shared prerequisites.
The resulting files are `brave_lite_shared.ninja`,
`brave_lite_graph.ninja`, and `brave_lite_partitions.ninja` in the build
directory. Their targets are `brave_lite_shared` and `brave_lite_group_1`
through `brave_lite_group_5`.

The saved graph from run `42004688079` produced 49,127 object targets and
23,159 shared object outputs. Counting the lines emitted by `ninja -t commands`
gives 148,849 compiler-command executions across five groups without a shared
bootstrap, versus 24,586 for the bootstrap and 25,922 across the groups after
it. This is an estimate based on that graph, not a timing or a completed build.
Siso can rewrite commands, and generated or non-C++ build work may still repeat.

Run `42013502753` tested a small version on three macOS runners: one saved the
shared prerequisite and two restored it, then each built its own group without
repeating the prerequisite. Siso's alternate Ninja file and streamed
checkpoint restore passed in that fixture.

The experimental `lite-shared-build.yml` workflow accepts an existing complete
workspace checkpoint, builds and checkpoints the real shared target, then
restores it on five compatible runners. Each runner saves its own group's
compiler cache in parts. If all five groups finish and upload their caches, the
workflow starts a separate staged assembly run that restores one cache at a
time and builds the five groups before linking the browser. Group cache
manifests include `actual_build_target` and `ninja_file` to distinguish them
from ordinary shards.

The restore must preserve timestamps, build metadata, source revision,
architecture, Xcode and SDK. The workflow remains experimental: a real
Chromium checkpoint, group cache handoff, disk capacity and final linking have
not yet been tested together. Interrupted bootstrap stages and uploaded group
cache parts remain available for inspection. The running build continues
using the existing staged workflow.
