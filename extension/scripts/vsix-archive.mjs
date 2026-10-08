import zlib from "node:zlib";

export function readZipEntries(archive) {
  const endOfCentralDirectory = findEndOfCentralDirectory(archive);
  const entryCount = archive.readUInt16LE(endOfCentralDirectory + 10);
  let offset = archive.readUInt32LE(endOfCentralDirectory + 16);
  const entries = new Map();

  for (let index = 0; index < entryCount; index += 1) {
    assertZipRange(archive, offset, 46, "central directory entry");
    if (archive.readUInt32LE(offset) !== 0x02014b50) {
      throw new Error("VSIX central directory is invalid.");
    }
    const flags = archive.readUInt16LE(offset + 8);
    const compressionMethod = archive.readUInt16LE(offset + 10);
    const compressedSize = archive.readUInt32LE(offset + 20);
    const fileNameLength = archive.readUInt16LE(offset + 28);
    const extraLength = archive.readUInt16LE(offset + 30);
    const commentLength = archive.readUInt16LE(offset + 32);
    const localHeaderOffset = archive.readUInt32LE(offset + 42);
    assertZipRange(archive, offset + 46, fileNameLength, "central directory filename");
    const name = archive.subarray(offset + 46, offset + 46 + fileNameLength).toString("utf8");
    entries.set(name, { flags, compressionMethod, compressedSize, localHeaderOffset });
    offset += 46 + fileNameLength + extraLength + commentLength;
  }

  return entries;
}

export function readZipEntry(archive, entry) {
  assertZipRange(archive, entry.localHeaderOffset, 30, "local file header");
  if (archive.readUInt32LE(entry.localHeaderOffset) !== 0x04034b50) {
    throw new Error("VSIX local file header is invalid.");
  }
  if ((entry.flags & 1) !== 0) {
    throw new Error("Encrypted VSIX entries are not supported.");
  }
  const fileNameLength = archive.readUInt16LE(entry.localHeaderOffset + 26);
  const extraLength = archive.readUInt16LE(entry.localHeaderOffset + 28);
  const payloadOffset = entry.localHeaderOffset + 30 + fileNameLength + extraLength;
  assertZipRange(archive, payloadOffset, entry.compressedSize, "VSIX entry data");
  const payload = archive.subarray(payloadOffset, payloadOffset + entry.compressedSize);

  if (entry.compressionMethod === 0) {
    return payload;
  }
  if (entry.compressionMethod === 8) {
    return zlib.inflateRawSync(payload);
  }
  throw new Error(`Unsupported VSIX compression method: ${entry.compressionMethod}.`);
}

function findEndOfCentralDirectory(archive) {
  const minimumOffset = Math.max(0, archive.length - 0xffff - 22);
  for (let offset = archive.length - 22; offset >= minimumOffset; offset -= 1) {
    if (
      archive.readUInt32LE(offset) === 0x06054b50 &&
      offset + 22 + archive.readUInt16LE(offset + 20) === archive.length
    ) {
      return offset;
    }
  }
  throw new Error("VSIX end-of-central-directory record is missing.");
}

function assertZipRange(archive, offset, length, label) {
  if (offset < 0 || length < 0 || offset + length > archive.length) {
    throw new Error(`VSIX ${label} is outside the archive bounds.`);
  }
}
