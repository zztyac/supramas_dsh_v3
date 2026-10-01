/**
 * SupraMAS bundle entry point.
 *
 * The bundle ships its skills, Python helpers, and schemas under `assets/`. They
 * live outside the user's workspace, so this provider registers the skills with
 * the harness and appends a runtime section pointing at the absolute asset
 * paths. Without that section the skill bodies would resolve
 * `$REPO_ROOT/tools/<helper>.py` against the user's own project and fail.
 *
 * Paths are resolved from `import.meta.url`, so nothing here depends on the
 * process working directory. Modeled on the shipped `@deepseek-ai/dsh-skill-office`
 * bundle, which solves the same problem for its LibreOffice helper.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";
import { BUNDLED_SKILL_RANK } from "@deepseek-ai/dsh-skill";

export const name = "supramas-dsh";
export const inject = ["skills"];

const PROVIDER = "supramas";

/** Extract the frontmatter fields and body from a SKILL.md. */
function parseFrontmatter(raw, path) {
  const match = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/u.exec(raw);
  if (match?.[1] === undefined) {
    throw new Error(`supramas-dsh: ${path} has no YAML frontmatter`);
  }
  const fields = {};
  for (const line of match[1].split(/\r?\n/)) {
    const pair = /^([A-Za-z0-9_-]+):\s*(.*)$/u.exec(line);
    if (pair) fields[pair[1]] = pair[2].trim();
  }
  if (!fields.description) {
    throw new Error(`supramas-dsh: ${path} has no description`);
  }
  return { fields, body: raw.slice(match[0].length).trim() };
}

/** Discover every `<skillsRoot>/<name>/SKILL.md` bundle. */
function discoverSkills(skillsRoot) {
  const found = [];
  for (const entry of readdirSync(skillsRoot, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const directory = join(skillsRoot, entry.name);
    const locator = join(directory, "SKILL.md");
    let raw;
    try {
      raw = readFileSync(locator, "utf8");
    } catch {
      continue; // A directory without SKILL.md is not a skill bundle.
    }
    const { fields } = parseFrontmatter(raw, locator);
    found.push({
      name: entry.name,
      description: fields.description,
      invocation: { modelInvocable: true, userInvocable: true },
      provider: PROVIDER,
      source: "bundled",
      rank: BUNDLED_SKILL_RANK,
      resourceBase: { kind: "directory", path: directory },
      locator,
    });
  }
  return found;
}

function listFiles(directory, extension) {
  try {
    return readdirSync(directory)
      .filter((entry) => entry.endsWith(extension))
      .sort();
  } catch {
    return [];
  }
}

/**
 * The runtime section appended to every skill body.
 *
 * The skill text computes `$REPO_ROOT/tools/...`, which belongs to the SupraMAS
 * source checkout. This section gives the absolute bundled paths instead.
 */
function runtimeSection(assetsRoot) {
  const details = {
    tools_dir: join(assetsRoot, "tools"),
    schemas_dir: join(assetsRoot, "schemas"),
    helpers: listFiles(join(assetsRoot, "tools"), ".py"),
    schemas: listFiles(join(assetsRoot, "schemas"), ".json"),
    run_helpers_with: "python3",
  };
  return [
    "",
    "## SupraMAS bundle resources",
    "",
    "This bundle ships its helpers outside your workspace. The instructions above",
    "may compute paths such as `$REPO_ROOT/tools/arxiv_fetch.py`; that path belongs",
    "to the SupraMAS source checkout and will not exist here. Use these absolute",
    "paths instead:",
    "",
    "```json",
    JSON.stringify({ supramas: details }, null, 2),
    "```",
    "",
    "The helpers are stdlib-only: no `pip install` step is required. If a helper",
    "named in the instructions above is missing from `helpers`, it is not shipped",
    "by this bundle — say so instead of inventing a command.",
  ].join("\n");
}

export function apply(ctx, config = {}) {
  const assetsRoot = config.assetRoot ?? fileURLToPath(new URL("../assets/", import.meta.url));
  if (!isAbsolute(assetsRoot)) {
    throw new Error("supramas-dsh: assetRoot must be an absolute directory");
  }
  const skillsRoot = join(assetsRoot, "skills");
  if (!statSync(skillsRoot).isDirectory()) {
    throw new Error(`supramas-dsh: skills are not bundled at ${skillsRoot}`);
  }

  const candidates = discoverSkills(skillsRoot);
  if (candidates.length === 0) {
    throw new Error(`supramas-dsh: no skills found under ${skillsRoot}`);
  }

  const runtime = runtimeSection(assetsRoot);
  const provider = {
    name: PROVIDER,
    list: () => Promise.resolve(candidates),
    async get(candidate, options) {
      const { rank: _rank, locator, ...summary } = candidate;
      const raw = await readFile(locator, { encoding: "utf8", signal: options.signal });
      return { ...summary, content: parseFrontmatter(raw, locator).body + runtime };
    },
  };

  ctx.skills.registerProvider(() => provider);
}
