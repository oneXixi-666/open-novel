import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { approvedAdvancedPaths, blockedAdvancedActionCopy, blockedAdvancedPaths, blockedAdvancedPlaceholderCopy } from "./advanced-paths.mjs";

const root = new URL("..", import.meta.url).pathname;
const distRoot = join(root, "dist");
const assetsRoot = join(distRoot, "assets");
function fail(message) {
  console.error(`FAIL ${message}`);
  process.exitCode = 1;
}

function pass(message) {
  console.log(`PASS ${message}`);
}

function read(path) {
  return readFileSync(path, "utf8");
}

function listAssets() {
  if (!existsSync(assetsRoot)) {
    fail("frontend dist assets are missing; run npm run build first");
    return [];
  }
  return readdirSync(assetsRoot)
    .map((name) => join(assetsRoot, name))
    .filter((path) => statSync(path).isFile() && path.endsWith(".js"));
}

function findMainEntry(indexHtml) {
  const match = indexHtml.match(/<script[^>]+src="\.\/assets\/([^"]+\.js)"/);
  return match ? join(assetsRoot, match[1]) : "";
}

const indexPath = join(distRoot, "index.html");
const indexHtml = existsSync(indexPath) ? read(indexPath) : "";
const assets = listAssets();
const mainEntry = findMainEntry(indexHtml);
const advancedAsset = assets.find((path) => path.includes("AdvancedPanels-"));
const pageAssets = assets.filter((path) => /(?:ModelPage|LibraryPage|MorePage|WritingPage|TodayPage|ReviewPage|ExportPage|ShelfPage)-/.test(path));

if (!indexHtml) {
  fail("dist index.html exists");
} else {
  pass("dist index.html exists");
}

if (!mainEntry || !existsSync(mainEntry)) {
  fail("dist main entry can be located");
} else {
  pass("dist main entry can be located");
}

if (!advancedAsset) {
  fail("advanced panels are emitted as a separate lazy asset");
} else {
  pass("advanced panels are emitted as a separate lazy asset");
}

if (mainEntry && existsSync(mainEntry)) {
  const mainEntryContent = read(mainEntry);
  const leaked = approvedAdvancedPaths.filter((path) => mainEntryContent.includes(path));
  const blocked = blockedAdvancedPaths.filter((path) => mainEntryContent.includes(path));
  if (leaked.length) {
    fail(`main entry contains advanced API paths: ${leaked.join(", ")}`);
  } else {
    pass("main entry does not contain advanced API paths");
  }
  if (blocked.length) {
    fail(`main entry contains blocked advanced paths: ${blocked.join(", ")}`);
  } else {
    pass("main entry does not contain blocked advanced paths");
  }
}

const pageLeaks = pageAssets
  .map((path) => ({
    name: path.split("/").pop() ?? path,
    leaked: approvedAdvancedPaths.filter((advancedPath) => read(path).includes(advancedPath))
  }))
  .filter((item) => item.leaked.length);
if (pageLeaks.length) {
  fail(`ordinary page chunks contain advanced API paths: ${pageLeaks.map((item) => item.name).join(", ")}`);
} else {
  pass("ordinary page chunks do not contain advanced API paths");
}

const blockedPageLeaks = pageAssets
  .map((path) => ({
    name: path.split("/").pop() ?? path,
    leaked: blockedAdvancedPaths.filter((advancedPath) => read(path).includes(advancedPath))
  }))
  .filter((item) => item.leaked.length);
if (blockedPageLeaks.length) {
  fail(`ordinary page chunks contain blocked advanced paths: ${blockedPageLeaks.map((item) => item.name).join(", ")}`);
} else {
  pass("ordinary page chunks do not contain blocked advanced paths");
}

const allAssetContents = assets.map((path) => ({ name: path.split("/").pop() ?? path, content: read(path) }));
const leakedActionCopy = allAssetContents
  .map((asset) => ({
    name: asset.name,
    leaked: blockedAdvancedActionCopy.filter((text) => asset.content.includes(text))
  }))
  .filter((item) => item.leaked.length);
if (leakedActionCopy.length) {
  fail(`dist assets contain high-risk advanced action copy: ${leakedActionCopy.map((item) => item.name).join(", ")}`);
} else {
  pass("dist assets exclude high-risk advanced action copy");
}

const leakedPlaceholderCopy = allAssetContents
  .map((asset) => ({
    name: asset.name,
    leaked: blockedAdvancedPlaceholderCopy.filter((text) => asset.content.includes(text))
  }))
  .filter((item) => item.leaked.length);
if (leakedPlaceholderCopy.length) {
  fail(`dist assets contain fake advanced placeholder copy: ${leakedPlaceholderCopy.map((item) => item.name).join(", ")}`);
} else {
  pass("dist assets exclude fake advanced placeholder copy");
}

if (advancedAsset) {
  const advancedContent = read(advancedAsset);
  const missing = approvedAdvancedPaths.filter((path) => !advancedContent.includes(path));
  const blocked = blockedAdvancedPaths.filter((path) => advancedContent.includes(path));
  if (missing.length) {
    fail(`advanced panels asset is missing approved paths: ${missing.join(", ")}`);
  } else {
    pass("advanced panels asset contains approved scoped paths");
  }
  if (blocked.length) {
    fail(`advanced panels asset contains blocked paths: ${blocked.join(", ")}`);
  } else {
    pass("advanced panels asset excludes blocked advanced paths");
  }
}

if (process.exitCode) {
  process.exit(process.exitCode);
}

console.log("\nAdvanced panels dist smoke passed.");
