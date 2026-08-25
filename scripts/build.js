const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const projectDir = path.join(__dirname, "..");
const signingFile = path.join(projectDir, ".env.signing");

if (!fs.existsSync(signingFile)) {
  console.error("Missing .env.signing. Copy .env.signing.example and add your certificate details.");
  process.exit(1);
}

for (const line of fs.readFileSync(signingFile, "utf8").split(/\r?\n/)) {
  const match = line.match(/^\s*(WIN_CSC_LINK|WIN_CSC_KEY_PASSWORD)\s*=\s*(.*)$/);
  if (match) process.env[match[1]] = match[2].trim();
}

const builder = path.join(projectDir, "node_modules", "electron-builder", "out", "cli", "cli.js");
const result = spawnSync(process.execPath, [builder, "--win", "portable"], {
  cwd: projectDir,
  env: process.env,
  stdio: "inherit",
});

process.exit(result.status ?? 1);
