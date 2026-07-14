import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ApiTestResult } from '../src/renderer/types';
import type { AppConfig } from '../src/main/config/config-store';

const mocks = vi.hoisted(() => ({
  probeWithSdk: vi.fn(),
}));

vi.mock('../src/main/agent/sdk-one-shot', () => ({
  probeWithSdk: mocks.probeWithSdk,
}));

import { runConfigApiTest } from '../src/main/config/config-test-routing';

function createConfig(): AppConfig {
  return {
    provider: 'openai',
    apiKey: 'sk-test',
    baseUrl: 'https://api.openai.com/v1',
    customProtocol: 'openai',
    model: 'gpt-4.1',
    activeProfileKey: 'openai',
    profiles: {},
    activeConfigSetId: 'default',
    configSets: [],
    agentCliPath: '',
    defaultWorkdir: '',
    globalSkillsPath: '',
    enableDevLogs: true,
    sandboxEnabled: false,
    enableThinking: false,
    isConfigured: true,
  };
}

describe('runConfigApiTest', () => {
  beforeEach(() => {
    mocks.probeWithSdk.mockReset();
  });

  it('routes all providers through probeWithSdk', async () => {
    const expected: ApiTestResult = { ok: true, latencyMs: 12 };
    mocks.probeWithSdk.mockResolvedValue(expected);

    const result = await runConfigApiTest(
      {
        provider: 'openai',
        apiKey: 'sk-test',
        model: 'gpt-4.1',
      },
      createConfig()
    );

    expect(result).toEqual(expected);
    expect(mocks.probeWithSdk).toHaveBeenCalledTimes(1);
  });

  it('routes ollama through probeWithSdk', async () => {
    const expected: ApiTestResult = { ok: true, latencyMs: 9 };
    mocks.probeWithSdk.mockResolvedValue(expected);

    const result = await runConfigApiTest(
      {
        provider: 'ollama',
        apiKey: '',
        baseUrl: 'http://localhost:11434',
        model: 'qwen3.5:0.8b',
      },
      {
        ...createConfig(),
        provider: 'ollama',
        apiKey: '',
        baseUrl: 'http://localhost:11434',
        model: 'qwen3.5:0.8b',
        activeProfileKey: 'ollama',
      }
    );

    expect(result).toEqual(expected);
    expect(mocks.probeWithSdk).toHaveBeenCalledTimes(1);
  });

  it('routes gemini through probeWithSdk', async () => {
    const expected: ApiTestResult = { ok: true, latencyMs: 18 };
    mocks.probeWithSdk.mockResolvedValue(expected);

    const result = await runConfigApiTest(
      {
        provider: 'gemini',
        customProtocol: 'gemini',
        apiKey: 'AIza-test',
        baseUrl: 'https://generativelanguage.googleapis.com',
        model: 'gemini/gemini-2.5-flash',
      },
      {
        ...createConfig(),
        provider: 'gemini',
        customProtocol: 'gemini',
        activeProfileKey: 'gemini',
        apiKey: 'AIza-test',
        baseUrl: 'https://generativelanguage.googleapis.com',
        model: 'gemini/gemini-2.5-flash',
      }
    );

    expect(result).toEqual(expected);
    expect(mocks.probeWithSdk).toHaveBeenCalledTimes(1);
  });

  it('returns failure when Claude Code executable is not found', async () => {
    const probeFailure: ApiTestResult = {
      ok: false,
      errorType: 'unknown',
      details: 'Claude Code executable not found. Please install @anthropic-ai/claude-code',
    };
    mocks.probeWithSdk.mockResolvedValue(probeFailure);

    const result = await runConfigApiTest(
      {
        provider: 'openai',
        apiKey: 'sk-test',
        model: 'gpt-4.1',
      },
      createConfig()
    );

    expect(result).toEqual(probeFailure);
    expect(mocks.probeWithSdk).toHaveBeenCalledTimes(1);
  });

  it('returns failure on protocol-level mismatch', async () => {
    const probeFailure: ApiTestResult = {
      ok: false,
      errorType: 'unknown',
      details: 'probe_response_mismatch:pong',
    };
    mocks.probeWithSdk.mockResolvedValue(probeFailure);

    const result = await runConfigApiTest(
      {
        provider: 'openai',
        apiKey: 'sk-test',
        model: 'gpt-4.1',
      },
      createConfig()
    );

    expect(result).toEqual(probeFailure);
    expect(mocks.probeWithSdk).toHaveBeenCalledTimes(1);
  });

  it('returns unauthorized without retry for explicit key', async () => {
    const probeFailure: ApiTestResult = {
      ok: false,
      errorType: 'unauthorized',
      details: '401 Unauthorized',
    };
    mocks.probeWithSdk.mockResolvedValue(probeFailure);

    const result = await runConfigApiTest(
      {
        provider: 'openai',
        apiKey: 'sk-explicit',
        model: 'gpt-4.1',
      },
      createConfig()
    );

    expect(result).toEqual(probeFailure);
    expect(mocks.probeWithSdk).toHaveBeenCalledTimes(1);
  });
});
