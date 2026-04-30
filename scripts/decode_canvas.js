#!/usr/bin/env node
/**
 * decode_canvas.js — decode a Figma Make canvas.fig binary into JSON.
 *
 * Adapted from albertsikkema/figma-make-extractor (MIT license, copyright 2026 Albert Sikkema).
 * Modified to:
 *   - take input/output paths via CLI args instead of hardcoded ./output/extracted
 *   - tolerate both 'fig-makee' and 'fig-makej' magic headers (Figma bumped the version)
 *   - exit non-zero with a clear message on format errors
 *
 * Usage: node decode_canvas.js <canvas.fig path> <output.json path>
 *
 * The output JSON is the raw decoded Kiwi message: a tree of nodes including
 * CODE_FILE entries with `name`, `codeFilePath`, and `sourceCode` fields.
 */
const fs = require('fs');
const pako = require('pako');
const fzstd = require('fzstd');
const kiwi = require('kiwi-schema');

const [, , inputPath, outputPath] = process.argv;
if (!inputPath || !outputPath) {
  console.error('Usage: node decode_canvas.js <canvas.fig> <output.json>');
  process.exit(2);
}

const buffer = fs.readFileSync(inputPath);
const data = new Uint8Array(buffer);
const view = new DataView(buffer.buffer, buffer.byteOffset, buffer.byteLength);

// Header: 9 magic bytes (fig-makee or fig-makej), 3 padding bytes, 4 chunk1-size bytes.
const magic = Buffer.from(data.slice(0, 9)).toString('ascii');
if (!magic.startsWith('fig-make')) {
  console.error(`Unexpected magic bytes: ${JSON.stringify(magic)} (expected to start with 'fig-make')`);
  process.exit(3);
}

let offset = 12;
const chunk1Size = view.getUint32(offset, true);
offset += 4;
const chunk1Data = data.slice(offset, offset + chunk1Size);
offset += chunk1Size;

// Chunk 1 = Kiwi schema, raw deflate compressed.
const schemaBytes = pako.inflateRaw(chunk1Data);

const chunk2Size = view.getUint32(offset, true);
offset += 4;
const chunk2Data = data.slice(offset, offset + chunk2Size);

// Chunk 2 = message data, zstd compressed.
const figmaData = fzstd.decompress(chunk2Data);

// Decode Kiwi message using the embedded schema.
const schemaObj = kiwi.decodeBinarySchema(schemaBytes);
const compiled = kiwi.compileSchema(schemaObj);
const message = compiled.decodeMessage(new Uint8Array(figmaData));

// Kiwi may emit BigInts; JSON.stringify can't handle them natively.
const replacer = (_key, value) => (typeof value === 'bigint' ? value.toString() : value);
fs.writeFileSync(outputPath, JSON.stringify(message, replacer, 2));

let codeFileCount = 0;
const walk = (node) => {
  if (!node || typeof node !== 'object') return;
  if (node.type === 'CODE_FILE') codeFileCount++;
  for (const v of Object.values(node)) {
    if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') walk(v);
  }
};
walk(message);
console.log(`Decoded canvas.fig: schema ${chunk1Size}->${schemaBytes.length} bytes, data ${chunk2Size}->${figmaData.length} bytes, ${codeFileCount} CODE_FILE nodes`);
