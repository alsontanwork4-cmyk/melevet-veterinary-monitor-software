import fs from "node:fs";
import path from "node:path";

const FRAME_SIZE = 124;
const PAYLOAD_SIZE = 122;
const CHANNEL_COUNT = 61;
const INDEX_HEADER_SIZE = 16;
const INDEX_ENTRY_SIZE = 16;
const INDEX_TRAILER_SIZE = 6;
const INVALID_U16 = new Set([65535, 21845]);

function usage() {
  console.error("Usage: node scripts/decode_trend_to_excel.mjs <TrendChartRecord.data> <TrendChartRecord.Index> [output.xlsx]");
  process.exit(1);
}

function decodeUnixSeconds(tsLo, tsHi) {
  return ((tsHi & 0x0000ffff) << 16) | (tsLo >>> 16);
}

function xmlEscape(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function colNameFromIndex(idxZeroBased) {
  let n = idxZeroBased + 1;
  let s = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    s = String.fromCharCode(65 + rem) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

function makeCellRef(rowIdx1Based, colIdx0Based) {
  return `${colNameFromIndex(colIdx0Based)}${rowIdx1Based}`;
}

function cellInlineStr(rowIdx1Based, colIdx0Based, value) {
  const ref = makeCellRef(rowIdx1Based, colIdx0Based);
  return `<c r=\"${ref}\" t=\"inlineStr\"><is><t>${xmlEscape(value)}</t></is></c>`;
}

function cellNumber(rowIdx1Based, colIdx0Based, value) {
  const ref = makeCellRef(rowIdx1Based, colIdx0Based);
  return `<c r=\"${ref}\"><v>${value}</v></c>`;
}

function cellEmpty(rowIdx1Based, colIdx0Based) {
  const ref = makeCellRef(rowIdx1Based, colIdx0Based);
  return `<c r=\"${ref}\"/>`;
}

function rowXml(rowIdx1Based, cellXmls) {
  return `<row r=\"${rowIdx1Based}\">${cellXmls.join("")}</row>`;
}

function buildWorksheetXml(rowsXml) {
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
    '<sheetData>',
    ...rowsXml,
    '</sheetData>',
    '</worksheet>',
  ].join("");
}

function buildContentTypesXml() {
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
    '<Default Extension="xml" ContentType="application/xml"/>',
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
    '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
    '<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
    '<Override PartName="/xl/worksheets/sheet4.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
    '</Types>',
  ].join("");
}

function buildRootRelsXml() {
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>',
    '</Relationships>',
  ].join("");
}

function buildWorkbookXml() {
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
    '<sheets>',
    '<sheet name="decode_notes" sheetId="1" r:id="rId1"/>',
    '<sheet name="index_header" sheetId="2" r:id="rId2"/>',
    '<sheet name="index_entries" sheetId="3" r:id="rId3"/>',
    '<sheet name="trend_frames" sheetId="4" r:id="rId4"/>',
    '</sheets>',
    '</workbook>',
  ].join("");
}

function buildWorkbookRelsXml() {
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>',
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>',
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>',
    '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet4.xml"/>',
    '</Relationships>',
  ].join("");
}

function makeCrc32Table() {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let j = 0; j < 8; j++) {
      c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
    }
    table[i] = c >>> 0;
  }
  return table;
}

const CRC32_TABLE = makeCrc32Table();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    c = CRC32_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function dosDateTime(now = new Date()) {
  const year = Math.max(1980, now.getFullYear());
  const dosTime = ((now.getHours() & 0x1f) << 11) | ((now.getMinutes() & 0x3f) << 5) | ((Math.floor(now.getSeconds() / 2)) & 0x1f);
  const dosDate = (((year - 1980) & 0x7f) << 9) | (((now.getMonth() + 1) & 0x0f) << 5) | (now.getDate() & 0x1f);
  return { dosTime, dosDate };
}

function buildZip(entries) {
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  const { dosTime, dosDate } = dosDateTime();

  for (const entry of entries) {
    const nameBuf = Buffer.from(entry.name.replace(/\\/g, "/"), "utf8");
    const dataBuf = Buffer.isBuffer(entry.data) ? entry.data : Buffer.from(entry.data, "utf8");
    const csum = crc32(dataBuf);

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt16LE(dosTime, 10);
    local.writeUInt16LE(dosDate, 12);
    local.writeUInt32LE(csum, 14);
    local.writeUInt32LE(dataBuf.length, 18);
    local.writeUInt32LE(dataBuf.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    local.writeUInt16LE(0, 28);

    localParts.push(local, nameBuf, dataBuf);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt16LE(dosTime, 12);
    central.writeUInt16LE(dosDate, 14);
    central.writeUInt32LE(csum, 16);
    central.writeUInt32LE(dataBuf.length, 20);
    central.writeUInt32LE(dataBuf.length, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    central.writeUInt32LE(0, 38);
    central.writeUInt32LE(offset, 42);

    centralParts.push(central, nameBuf);

    offset += local.length + nameBuf.length + dataBuf.length;
  }

  const centralSize = centralParts.reduce((acc, b) => acc + b.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralSize, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);

  return Buffer.concat([...localParts, ...centralParts, end]);
}

function parseIndex(indexBytes) {
  if (indexBytes.length < INDEX_HEADER_SIZE + INDEX_TRAILER_SIZE) {
    throw new Error("Index file too small");
  }

  const version = indexBytes.readUInt32LE(0);
  const bufferSize = indexBytes.readUInt32LE(4);
  const payloadSize = indexBytes.readUInt32LE(8);
  const padding = indexBytes.readUInt32LE(12);

  const payloadLen = indexBytes.length - INDEX_HEADER_SIZE - INDEX_TRAILER_SIZE;
  if (payloadLen % INDEX_ENTRY_SIZE !== 0) {
    throw new Error("Index payload is not aligned to 16-byte entries");
  }

  const entries = [];
  const rollbackIndices = [];
  let prevUnix = null;

  for (let i = 0; i < payloadLen / INDEX_ENTRY_SIZE; i++) {
    const off = INDEX_HEADER_SIZE + i * INDEX_ENTRY_SIZE;
    const flags = indexBytes.readUInt32LE(off + 0);
    const ptr = indexBytes.readUInt32LE(off + 4);
    const tsLo = indexBytes.readUInt32LE(off + 8);
    const tsHi = indexBytes.readUInt32LE(off + 12);

    const unixSeconds = decodeUnixSeconds(tsLo, tsHi);
    if (prevUnix !== null && unixSeconds < prevUnix) {
      rollbackIndices.push(i);
    }
    prevUnix = unixSeconds;

    entries.push({
      frame_index: i,
      flags,
      ptr,
      ts_lo: tsLo,
      ts_hi: tsHi,
      unix_seconds: unixSeconds,
      timestamp_utc: new Date(unixSeconds * 1000).toISOString(),
    });
  }

  return {
    header: { version, buffer_size: bufferSize, payload_size: payloadSize, padding },
    entries,
    trailer_hex: indexBytes.subarray(indexBytes.length - INDEX_TRAILER_SIZE).toString("hex"),
    rollbackIndices,
  };
}

function parseTrendData(dataBytes, indexEntries) {
  if (dataBytes.length % FRAME_SIZE !== 0) {
    throw new Error("Trend data file size is not aligned to 124-byte frames");
  }

  const frameCount = dataBytes.length / FRAME_SIZE;
  if (frameCount !== indexEntries.length) {
    throw new Error(`Frame count mismatch: data=${frameCount}, index=${indexEntries.length}`);
  }

  const frames = [];
  for (let i = 0; i < frameCount; i++) {
    const frameOff = i * FRAME_SIZE;
    const payload = dataBytes.subarray(frameOff, frameOff + PAYLOAD_SIZE);
    const trailer2 = dataBytes.subarray(frameOff + PAYLOAD_SIZE, frameOff + FRAME_SIZE).toString("hex");

    const values = new Array(CHANNEL_COUNT);
    for (let ch = 0; ch < CHANNEL_COUNT; ch++) {
      const off = ch * 2;
      const raw = payload.readUInt16BE(off);
      values[ch] = INVALID_U16.has(raw) ? null : raw;
    }

    frames.push({
      frame_index: i,
      ptr: indexEntries[i].ptr,
      timestamp_utc: indexEntries[i].timestamp_utc,
      values,
      frame_tail_hex: trailer2,
    });
  }
  return frames;
}

function buildDecodeNotesSheet(indexInfo, frameCount) {
  const rows = [];
  const items = [
    ["file_type", "TrendChartRecord reverse-engineering notes"],
    ["index_header_size", INDEX_HEADER_SIZE],
    ["index_entry_size", INDEX_ENTRY_SIZE],
    ["index_trailer_size", INDEX_TRAILER_SIZE],
    ["data_frame_size", FRAME_SIZE],
    ["data_payload_size", PAYLOAD_SIZE],
    ["channel_count", CHANNEL_COUNT],
    ["value_endianness", "big-endian u16"],
    ["invalid_u16_values", "65535 (0xFFFF), 21845 (0x5555) -> blank"],
    ["decoded_frame_count", frameCount],
    ["index_entry_count", indexInfo.entries.length],
    ["index_timestamp_rollback_count", indexInfo.rollbackIndices.length],
    ["index_trailer_hex", indexInfo.trailer_hex],
  ];

  rows.push(rowXml(1, [cellInlineStr(1, 0, "field"), cellInlineStr(1, 1, "value")]));
  for (let i = 0; i < items.length; i++) {
    const rowNo = i + 2;
    const [k, v] = items[i];
    const cells = [cellInlineStr(rowNo, 0, k)];
    if (typeof v === "number") cells.push(cellNumber(rowNo, 1, v));
    else cells.push(cellInlineStr(rowNo, 1, v));
    rows.push(rowXml(rowNo, cells));
  }

  return buildWorksheetXml(rows);
}

function buildIndexHeaderSheet(indexInfo) {
  const rows = [];
  rows.push(rowXml(1, [cellInlineStr(1, 0, "field"), cellInlineStr(1, 1, "value")]));

  const pairs = [
    ["version", indexInfo.header.version],
    ["buffer_size", indexInfo.header.buffer_size],
    ["payload_size", indexInfo.header.payload_size],
    ["padding", indexInfo.header.padding],
    ["entry_count", indexInfo.entries.length],
    ["trailer_hex", indexInfo.trailer_hex],
  ];

  for (let i = 0; i < pairs.length; i++) {
    const rowNo = i + 2;
    const [key, val] = pairs[i];
    const cells = [cellInlineStr(rowNo, 0, key)];
    if (typeof val === "number") cells.push(cellNumber(rowNo, 1, val));
    else cells.push(cellInlineStr(rowNo, 1, val));
    rows.push(rowXml(rowNo, cells));
  }

  return buildWorksheetXml(rows);
}

function buildIndexEntriesSheet(indexInfo) {
  const rows = [];
  const headers = ["frame_index", "flags", "ptr", "ts_lo", "ts_hi", "unix_seconds", "timestamp_utc", "is_rollback"];
  rows.push(rowXml(1, headers.map((h, i) => cellInlineStr(1, i, h))));

  const rollbackSet = new Set(indexInfo.rollbackIndices);
  for (let i = 0; i < indexInfo.entries.length; i++) {
    const rowNo = i + 2;
    const e = indexInfo.entries[i];
    const cells = [
      cellNumber(rowNo, 0, e.frame_index),
      cellNumber(rowNo, 1, e.flags),
      cellNumber(rowNo, 2, e.ptr),
      cellNumber(rowNo, 3, e.ts_lo),
      cellNumber(rowNo, 4, e.ts_hi),
      cellNumber(rowNo, 5, e.unix_seconds),
      cellInlineStr(rowNo, 6, e.timestamp_utc),
      rollbackSet.has(i) ? cellNumber(rowNo, 7, 1) : cellNumber(rowNo, 7, 0),
    ];
    rows.push(rowXml(rowNo, cells));
  }

  return buildWorksheetXml(rows);
}

function buildTrendFramesSheet(frames) {
  const rows = [];
  const headers = ["frame_index", "ptr", "timestamp_utc"];
  for (let ch = 0; ch < CHANNEL_COUNT; ch++) {
    headers.push(`ch${String(ch).padStart(2, "0")}_be_u16_o${String(ch * 2).padStart(3, "0")}`);
  }
  headers.push("frame_tail_hex");

  rows.push(rowXml(1, headers.map((h, i) => cellInlineStr(1, i, h))));

  for (let i = 0; i < frames.length; i++) {
    const rowNo = i + 2;
    const f = frames[i];
    const cells = [
      cellNumber(rowNo, 0, f.frame_index),
      cellNumber(rowNo, 1, f.ptr),
      cellInlineStr(rowNo, 2, f.timestamp_utc),
    ];

    for (let ch = 0; ch < CHANNEL_COUNT; ch++) {
      const col = 3 + ch;
      const v = f.values[ch];
      cells.push(v === null ? cellEmpty(rowNo, col) : cellNumber(rowNo, col, v));
    }

    cells.push(cellInlineStr(rowNo, 3 + CHANNEL_COUNT, f.frame_tail_hex));
    rows.push(rowXml(rowNo, cells));
  }

  return buildWorksheetXml(rows);
}

function main() {
  const [, , dataPathArg, indexPathArg, outPathArg] = process.argv;
  if (!dataPathArg || !indexPathArg) usage();

  const dataPath = path.resolve(dataPathArg);
  const indexPath = path.resolve(indexPathArg);
  const outputPath = outPathArg
    ? path.resolve(outPathArg)
    : path.resolve(path.dirname(dataPath), "TrendChartRecord_decoded.xlsx");

  const dataBytes = fs.readFileSync(dataPath);
  const indexBytes = fs.readFileSync(indexPath);

  const indexInfo = parseIndex(indexBytes);
  const frames = parseTrendData(dataBytes, indexInfo.entries);

  const files = [
    { name: "[Content_Types].xml", data: buildContentTypesXml() },
    { name: "_rels/.rels", data: buildRootRelsXml() },
    { name: "xl/workbook.xml", data: buildWorkbookXml() },
    { name: "xl/_rels/workbook.xml.rels", data: buildWorkbookRelsXml() },
    { name: "xl/worksheets/sheet1.xml", data: buildDecodeNotesSheet(indexInfo, frames.length) },
    { name: "xl/worksheets/sheet2.xml", data: buildIndexHeaderSheet(indexInfo) },
    { name: "xl/worksheets/sheet3.xml", data: buildIndexEntriesSheet(indexInfo) },
    { name: "xl/worksheets/sheet4.xml", data: buildTrendFramesSheet(frames) },
  ];

  const zip = buildZip(files);
  fs.writeFileSync(outputPath, zip);

  console.log(JSON.stringify({
    output: outputPath,
    frame_count: frames.length,
    entry_count: indexInfo.entries.length,
    rollback_count: indexInfo.rollbackIndices.length,
    first_timestamp_utc: indexInfo.entries[0]?.timestamp_utc ?? null,
    last_timestamp_utc: indexInfo.entries[indexInfo.entries.length - 1]?.timestamp_utc ?? null,
  }, null, 2));
}

main();
