#!/usr/bin/env node
// Package the Trainer Capture browser extension (browser-extension/) into
// dist/trainer-capture-extension.zip.
//
// The archive is written by this script itself (zlib deflate + a minimal ZIP
// container) so packaging has no dependency on platform tools, and fixed
// entry timestamps keep the output byte-stable between identical runs.

import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deflateRawSync } from 'node:zlib';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, '..');
const sourceDir = join(repoRoot, 'browser-extension');
const outputPath = join(repoRoot, 'dist', 'trainer-capture-extension.zip');

// Only shipping-relevant entries are packaged; anything else in the directory
// (screenshots, scratch files, OS metadata) is deliberately left out.
const INCLUDE_ROOTS = ['manifest.json', 'background.js', 'shared.js', 'popup', 'icons', 'README.md'];
const EXCLUDED_PATTERNS = [
  /^\.DS_Store$/,
  /^\._/,
  /\.map$/,
  /\.zip$/,
  /\.tmp$/,
  /~$/
];

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) {
      value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[index] = value >>> 0;
  }
  return table;
})();

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function collectFiles(directory, prefix = '') {
  const entries = [];
  for (const name of readdirSync(directory).sort()) {
    if (EXCLUDED_PATTERNS.some((pattern) => pattern.test(name))) {
      continue;
    }
    const absolute = join(directory, name);
    const archiveName = prefix ? `${prefix}/${name}` : name;
    const stats = statSync(absolute);
    if (stats.isDirectory()) {
      entries.push(...collectFiles(absolute, archiveName));
    } else if (stats.isFile()) {
      entries.push({ name: archiveName, absolute, size: stats.size });
    }
  }
  return entries;
}

function buildZip(files) {
  const localChunks = [];
  const centralChunks = [];
  let offset = 0;

  for (const file of files) {
    const nameBytes = Buffer.from(file.name, 'utf8');
    const data = readFileSync(file.absolute);
    const compressed = deflateRawSync(data, { level: 9 });
    const checksum = crc32(data);

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4); // version needed to extract
    local.writeUInt16LE(0x0800, 6); // UTF-8 file names
    local.writeUInt16LE(8, 8); // deflate
    local.writeUInt16LE(0, 10); // fixed 1980-01-01 timestamp
    local.writeUInt16LE(0x21, 12);
    local.writeUInt32LE(checksum, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    local.writeUInt16LE(0, 28);
    localChunks.push(local, nameBytes, compressed);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(0x031e, 4); // made by UNIX, 3.0
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(8, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(0x21, 14);
    central.writeUInt32LE(checksum, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt16LE(0, 30); // extra length
    central.writeUInt16LE(0, 32); // comment length
    central.writeUInt16LE(0, 34); // disk number
    central.writeUInt16LE(0, 36); // internal attributes
    // Unix mode 0644 in the high 16 bits; `>>> 0` keeps the shift unsigned.
    central.writeUInt32LE((0o100644 << 16) >>> 0, 38); // external attributes
    central.writeUInt32LE(offset, 42);
    centralChunks.push(central, nameBytes);

    offset += local.length + nameBytes.length + compressed.length;
  }

  const centralSize = centralChunks.reduce((total, chunk) => total + chunk.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(centralSize, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);

  return Buffer.concat([...localChunks, ...centralChunks, end]);
}

function assertManifestReferences() {
  const manifestPath = join(sourceDir, 'manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  const referenced = [
    manifest.background?.service_worker,
    manifest.action?.default_popup,
    ...Object.values(manifest.icons ?? {}),
    ...Object.values(manifest.action?.default_icon ?? {})
  ].filter((value) => typeof value === 'string' && value.length > 0);

  const problems = [];
  for (const reference of new Set(referenced)) {
    const absolute = join(sourceDir, reference);
    try {
      if (!statSync(absolute).isFile()) {
        problems.push(reference);
      }
    } catch {
      problems.push(reference);
    }
  }
  if (problems.length > 0) {
    throw new Error(`manifest.json references missing files: ${problems.join(', ')}`);
  }
  return manifest;
}

function main() {
  const manifest = assertManifestReferences();

  const roots = INCLUDE_ROOTS.map((name) => join(sourceDir, name));
  const files = [];
  for (const root of roots) {
    let stats;
    try {
      stats = statSync(root);
    } catch {
      throw new Error(`Missing packaging input: ${relative(repoRoot, root)}`);
    }
    if (stats.isDirectory()) {
      files.push(...collectFiles(root, relative(sourceDir, root).split(sep).join('/')));
    } else {
      files.push({ name: relative(sourceDir, root).split(sep).join('/'), absolute: root, size: stats.size });
    }
  }
  files.sort((first, second) => first.name.localeCompare(second.name));

  const zip = buildZip(files);
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, zip);

  console.log(`Trainer Capture v${manifest.version} → ${relative(repoRoot, outputPath)}`);
  for (const file of files) {
    console.log(`  ${file.name} (${file.size} bytes)`);
  }
  console.log(`  ${files.length} files, ${zip.length} bytes packed`);
}

main();
