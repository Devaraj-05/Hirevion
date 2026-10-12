// Reads the gitignored root `.env` into process.env without overriding what is already set.
// A git worktree has no `.env` of its own, so the main checkout's is read too.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

function git(args, cwd) {
  try {
    return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}

/** The repository root, and the main checkout's root when this is a linked worktree. */
export function repoRoots(from) {
  const top = git(["rev-parse", "--show-toplevel"], from);
  const common = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], from);
  const main = common ? dirname(common) : "";
  return [top, main].filter((path, index, all) => path && all.indexOf(path) === index);
}

export function loadDotEnv(from) {
  const loaded = [];
  for (const root of repoRoots(from)) {
    const file = resolve(root, ".env");
    if (!existsSync(file)) continue;
    for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
      const match = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/.exec(line);
      if (!match || line.trimStart().startsWith("#")) continue;
      const [, name, raw] = match;
      const value = raw.replace(/^(['"])(.*)\1$/, "$2");
      if (process.env[name] === undefined) process.env[name] = value;
    }
    loaded.push(file);
  }
  return loaded;
}
