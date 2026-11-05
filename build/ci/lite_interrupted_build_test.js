import assert from 'node:assert/strict'
import test from 'node:test'
import {
  shouldCheckGnGraph,
  shouldCleanInterruptedBuild,
} from '../commands/lib/interruptedBuild.js'

test('ordinary interrupted CI builds retain their existing behavior', () => {
  assert.equal(shouldCleanInterruptedBuild(true, false, true, false), true)
  assert.equal(shouldCleanInterruptedBuild(false, false, true, false), false)
  assert.equal(shouldCleanInterruptedBuild(true, true, true, false), false)
  assert.equal(shouldCleanInterruptedBuild(true, false, false, false), false)
})

test('staged builds retain output after interruption', () => {
  assert.equal(shouldCleanInterruptedBuild(true, false, true, true), false)
})

test('CI rechecks GN unless a previously validated graph is restored', () => {
  assert.equal(shouldCheckGnGraph(true, false), true)
  assert.equal(shouldCheckGnGraph(true, true), false)
  assert.equal(shouldCheckGnGraph(false, false), false)
})
