import { describe, expect, it } from 'vitest';
import {
  isScrollNearBottom,
  resolveSessionScrollTop,
} from '../src/renderer/utils/chat-scroll-position';

describe('chat session scroll restoration', () => {
  it('defaults a session without history to the bottom', () => {
    expect(resolveSessionScrollTop(undefined, 1200, 400)).toBe(800);
  });

  it('restores a saved session position', () => {
    expect(resolveSessionScrollTop(275, 1200, 400)).toBe(275);
  });

  it('clamps stale positions after content shrinks', () => {
    expect(resolveSessionScrollTop(900, 700, 400)).toBe(300);
  });

  it('recognizes the auto-scroll threshold', () => {
    expect(isScrollNearBottom(720, 1200, 400)).toBe(true);
    expect(isScrollNearBottom(719, 1200, 400)).toBe(false);
  });
});
