import { describe, expect, it } from 'vitest';
import { escapeThinkTags } from '../src/renderer/components/message/ThinkingBlock';

describe('escapeThinkTags', () => {
  it('escapes opening and closing think tags for Markdown rendering', () => {
    expect(escapeThinkTags('<think>reasoning</think>')).toBe(
      '&lt;think&gt;reasoning&lt;/think&gt;'
    );
  });

  it('leaves ordinary and malformed text unchanged', () => {
    expect(escapeThinkTags('normal text <thinking>')).toBe('normal text <thinking>');
  });

  it('does not double-escape existing entities', () => {
    expect(escapeThinkTags('&lt;think&gt;reasoning&lt;/think&gt;')).toBe(
      '&lt;think&gt;reasoning&lt;/think&gt;'
    );
  });
});
