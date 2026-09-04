// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { createLineDecoder } from './ndjson';

describe('createLineDecoder', () => {
  it('单条完整行', () => {
    const decode = createLineDecoder();
    expect(decode('{"a":1}\n')).toEqual(['{"a":1}']);
  });

  it('跨块半行拼接', () => {
    const decode = createLineDecoder();
    expect(decode('{"js')).toEqual([]);
    expect(decode('onrpc":"2.0"}\n')).toEqual(['{"jsonrpc":"2.0"}']);
  });

  it('单块多行', () => {
    const decode = createLineDecoder();
    expect(decode('{"a":1}\n{"b":2}\n{"c":3}\n')).toEqual(['{"a":1}', '{"b":2}', '{"c":3}']);
  });

  it('空行跳过并保留尾部半行', () => {
    const decode = createLineDecoder();
    expect(decode('{"a":1}\n\n{"b":2}\n{"part')).toEqual(['{"a":1}', '{"b":2}']);
    expect(decode('ial":true}\n')).toEqual(['{"partial":true}']);
  });
});
