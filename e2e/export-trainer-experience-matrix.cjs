"use strict";

// Keep every verification layer on the same authored journey list. This
// program intentionally only serializes the matrix; it does not run Preview.
const { SCENARIOS } = require("./trainer-experience-matrix");

process.stdout.write(JSON.stringify(SCENARIOS));
