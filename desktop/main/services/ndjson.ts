/** NDJSON 行分帧：字符串块 → 完整行（与 service 侧 LineAssembler 语义一致）。 */

export type LineDecoder = (chunk: string) => string[];

export function createLineDecoder(): LineDecoder {
  let buffer = '';
  return (chunk: string): string[] => {
    buffer += chunk;
    const lines: string[] = [];
    let newlineIndex = buffer.indexOf('\n');
    while (newlineIndex >= 0) {
      const line = buffer.slice(0, newlineIndex);
      buffer = buffer.slice(newlineIndex + 1);
      if (line.length > 0) lines.push(line);
      newlineIndex = buffer.indexOf('\n');
    }
    return lines;
  };
}
