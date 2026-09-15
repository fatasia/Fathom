import { afterEach, describe, expect, it, vi } from 'vitest'

import { submitTurnFeedback } from './api'

describe('feedback API contract', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('binds a rating to the current conversation turn', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          feedback_id: 'fb_01',
          source: 'self_ui',
          rating: 'dislike',
          category: 'general',
          sentiment: 'negative',
          emotion: 'dissatisfied',
          status: 'open',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await submitTurnFeedback('chat_0123456789abcdefghij', 'turn_01', 'dislike')

    expect(result.rating).toBe('dislike')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/query/conversations/chat_0123456789abcdefghij/turns/turn_01/feedback',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ rating: 'dislike', content: '' }),
      }),
    )
  })
})
