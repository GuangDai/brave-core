// Generate the same GN graph as the macOS build without invoking a compiler.
import config from '../commands/lib/config.ts'
import util from '../commands/lib/util.js'
import branding from '../commands/lib/branding.js'
import * as buildUtils from '../commands/lib/buildUtils.ts'

config.buildConfig = 'Static'
config.update({
  target_arch: 'arm64',
  skip_signing: true,
  gn: [
    'symbol_level:0',
    'cc_wrapper:ccache',
    'use_clang_modules:false',
    'enable_precompiled_headers:false',
    'enable_brave_wallet:false',
    'enable_brave_rewards:false',
    'enable_brave_vpn_v1:false',
    'enable_brave_vpn_v2:false',
    'enable_ai_chat:false',
  ],
})
buildUtils.checkVersionsMatch()
util.touchOverriddenFiles()
branding.update()
await util.generateNinjaFiles()
