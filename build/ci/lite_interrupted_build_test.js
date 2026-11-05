import assert from 'node:assert/strict'
import test from 'node:test'
import { shouldCleanInterruptedBuild } from '../commands/lib/interruptedBuild.js'

test('ordinary interrupted CI builds retain their existing behavior', () => {
  assert.equal(shouldCleanInterruptedBuild(true, false, true, false), true)
  assert.equal(shouldCleanInterruptedBuild(false, false, true, false), false)
  assert.equal(shouldCleanInterruptedBuild(true, true, true, false), false)
  assert.equal(shouldCleanInterruptedBuild(true, false, false, false), false)
})

test('staged builds retain output after interruption', () => {
  assert.equal(shouldCleanInterruptedBuild(true, false, true, true), false)
})
