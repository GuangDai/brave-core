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

The intended next experiment is to build the shared target on one macOS runner,
save its complete workspace, restore it on five compatible runners, and build
one group per runner. Their compiler caches would then be used by the final
browser build. The restore must preserve timestamps, build metadata, source
revision, architecture, Xcode and SDK. This workflow is not integrated into the
production build: test a real macOS checkpoint, Siso's alternate Ninja file,
cache handoff, disk capacity and final linking before relying on it. The
running build continues using the existing staged workflow.
