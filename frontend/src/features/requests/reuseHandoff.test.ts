import { beforeEach, describe, expect, it } from 'vitest'

import {
  buildReuseHandoff,
  clearReuseHandoff,
  consumeReuseHandoff,
  publishReuseHandoff,
  type SafeInfo,
} from '@/features/requests/reuseHandoff'

const safeInfo = {
  request_id: 'must-not-copy',
  status: 'ACCEPTED',
  raw_title: '原始标题',
  title: '安全标题',
  aliases: ['别名'],
  season: 1,
  season_raw: 'S1',
  season_evidence: '证据',
  mikan_collection: { title: '真实合集', bangumi_id: '2353' },
  selected_subtitle_group: '字幕组',
  filter_rule: { must_contain: '1080p', must_not_contain: 'SP', use_regex: false, case_sensitive: false },
  folder_name: '目录',
  storage_profile: 'storage',
  subtitle_groups: [],
  resources: { selected_subtitle_group: '字幕组', valid_resource_count: 1, invalid_resource_count: 0, complete_resource_count: 1 },
  total_episodes: null,
  updated_episode: null,
  updated_episode_status: 'NOT_IMPLEMENTED',
  history_summary: [],
  ab_status: { submitted: false, success: null, ab_subscription_id: null, error_type: null },
} as SafeInfo

describe('reuseHandoff (US-300)', () => {
  beforeEach(() => clearReuseHandoff())

  it('builds only a public one-shot whitelist', () => {
    const handoff = buildReuseHandoff(safeInfo)
    expect(handoff).toEqual({
      title: '安全标题',
      mikanBangumiId: '2353',
      suggestion: {
        selectedSubtitleGroup: '字幕组',
        filterRule: { mustContain: '1080p', mustNotContain: 'SP', useRegex: false, caseSensitive: false },
        expectedFolderName: '目录',
      },
    })
    expect(JSON.stringify(handoff)).not.toContain('must-not-copy')
    expect(JSON.stringify(handoff)).not.toContain('storage_profile')
  })

  it('consumes and clears the handoff exactly once', () => {
    const handoff = buildReuseHandoff(safeInfo)
    expect(handoff).not.toBeNull()
    publishReuseHandoff(handoff!)
    expect(consumeReuseHandoff()).toEqual(handoff)
    expect(consumeReuseHandoff()).toBeNull()
  })

  it('rejects a safe-info response without a valid public collection id', () => {
    expect(buildReuseHandoff({ ...safeInfo, mikan_collection: { title: '合集', bangumi_id: 'https://private.invalid/1' } })).toBeNull()
  })
})
