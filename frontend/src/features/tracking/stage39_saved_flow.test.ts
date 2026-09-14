import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const trackingView = readFileSync(resolve(__dirname, 'TrackingView.vue'), 'utf8')
const settingsView = readFileSync(resolve(__dirname, '../settings/SettingsView.vue'), 'utf8')

describe('Stage 39 saved-connection migration red contract', () => {
  it('TrackingView does not retain the deleted credential dialog or unsafe legacy cast', () => {
    expect(trackingView).not.toContain('CredentialSessionDialog')
    expect(trackingView).not.toContain('sessionConfig.value as any')
    expect(trackingView).not.toContain("'/api/v1/autobangumi/capabilities'")
  })

  it('settings uses saved connection operations and handles configuration conflicts by rereading', () => {
    expect(settingsView).toContain('/api/v1/settings/autobangumi')
    expect(settingsView).toContain('configuration_revision')
    expect(settingsView).toContain('409')
    expect(settingsView).toContain('重新读取')
    expect(settingsView).not.toContain('/api/v1/autobangumi/test-connection')
  })
})
