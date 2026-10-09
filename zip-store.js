/* Portable ZIP32 STORE writer. Preserves original screenshot bytes; no dependency/CDN. */
const utf8 = new TextEncoder();
const table = new Uint32Array(256);
for (let n = 0; n < 256; n++) {
  let c = n;
  for (let j = 0; j < 8; j++) c = c & 1 ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
  table[n] = c >>> 0;
}
function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = table[(c ^ bytes[i]) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
const u16 = (v) => [v & 255, (v >>> 8) & 255];
const u32 = (v) => [v & 255, (v >>> 8) & 255, (v >>> 16) & 255, (v >>> 24) & 255];
function writeHeader(values) { return Uint8Array.from(values); }
function checkName(name) {
  if (!name || name.startsWith('/') || name.includes('\\') || name.includes('..') || /[\x00-\x1f]/.test(name))
    throw new Error(`安全でないZIP内ファイル名: ${name}`);
}
/** entries: {name:string, bytes:Uint8Array} */
export function makeZip(entries) {
  if (!Array.isArray(entries) || !entries.length || entries.length > 65535) throw new Error('ZIPのファイル数が不正です');
  const used = new Set(), chunks = [], central = [];
  let offset = 0, centralSize = 0;
  for (const {name, bytes} of entries) {
    checkName(name);
    if (used.has(name)) throw new Error(`同じZIPパスが重複しています: ${name}`);
    used.add(name);
    if (!(bytes instanceof Uint8Array) || bytes.length > 0xffffffff) throw new Error(`${name}: ZIP32サイズ上限超過`);
    const nm = utf8.encode(name);
    if (nm.length > 65535) throw new Error(`${name}: ファイル名が長すぎます`);
    const size = bytes.length, crc = crc32(bytes);
    const local = writeHeader([
      ...u32(0x04034b50), ...u16(20), ...u16(0x0800), ...u16(0), ...u16(0), ...u16(0),
      ...u32(crc), ...u32(size), ...u32(size), ...u16(nm.length), ...u16(0)
    ]);
    chunks.push(local, nm, bytes);
    const center = writeHeader([
      ...u32(0x02014b50), ...u16(20), ...u16(20), ...u16(0x0800), ...u16(0),
      ...u16(0), ...u16(0), ...u32(crc), ...u32(size), ...u32(size),
      ...u16(nm.length), ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(0), ...u32(offset)
    ]);
    central.push(center, nm); centralSize += center.length + nm.length;
    offset += local.length + nm.length + size;
    if (offset > 0xffffffff) throw new Error('ZIP32サイズ上限を超えました');
  }
  if (offset + centralSize + 22 > 0xffffffff) throw new Error('ZIP32サイズ上限を超えました');
  const footer = writeHeader([
    ...u32(0x06054b50), ...u16(0), ...u16(0), ...u16(entries.length),
    ...u16(entries.length), ...u32(centralSize), ...u32(offset), ...u16(0)
  ]);
  return new Blob([...chunks, ...central, footer], {type: 'application/zip'});
}
