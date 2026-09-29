import { posix } from "node:path";

/**
 * The layer rules for apps/web/src, checked by architecture.test.ts over the real tree.
 *
 *   app       route files only; imports features, shared, entities and server
 *   features  one directory per screen family; imports shared, entities, server and itself
 *   entities  pure domain types and mappers; imports shared/lib and itself, never React or next
 *   server    server-only modules; imports server, shared and entities, never features
 *   shared    isomorphic code; imports shared only, never a server module
 *   root      proxy.ts and instrumentation.ts; import server, shared and entities
 *
 * A client component ("use client") imports shared, entities and its own directory subtree,
 * so nothing server-side can reach a client bundle through a feature. Imports of the
 * contracts package from app code are type-only.
 */
export type Layer = "app" | "features" | "entities" | "server" | "shared" | "root" | "test";

export interface SourceFile {
  /** Path relative to src, posix separators. */
  path: string;
  source: string;
}

export interface ImportRef {
  specifier: string;
  typeOnly: boolean;
}

export interface Violation {
  file: string;
  specifier: string;
  reason: string;
}

const LAYERS: readonly Layer[] = ["app", "features", "entities", "server", "shared", "test"];

const ALLOWED: Record<Layer, readonly Layer[]> = {
  app: ["features", "shared", "entities", "server"],
  features: ["features", "shared", "entities", "server"],
  entities: ["entities", "shared"],
  server: ["server", "shared", "entities"],
  shared: ["shared"],
  root: ["server", "shared", "entities"],
  test: ["app", "features", "entities", "server", "shared", "test", "root"],
};

/** Modules that only work on the server; shared and entities code must not import them. */
const SERVER_ONLY_MODULES = ["server-only", "next/headers", "next/server", "next/cache"];

/** Browser and framework modules that pure entity code must not depend on. */
const ENTITY_FORBIDDEN_PREFIXES = ["react", "next", "server-only", "@compliancewatch/ui"];

const ASSET_EXTENSIONS = /\.(css|scss|svg|png|jpg|jpeg|gif|webp|ico|woff2?)$/;
const CODE_EXTENSIONS = /\.(tsx?|jsx?|mts|cts)$/;

export function layerOf(path: string): Layer {
  const [head] = path.split("/");
  if (head !== undefined && (LAYERS as readonly string[]).includes(head) && path.includes("/")) {
    return head as Layer;
  }
  return "root";
}

/** The feature (or entity) directory a path belongs to, for example "features/home". */
export function moduleRootOf(path: string): string | undefined {
  const [head, name] = path.split("/");
  if ((head === "features" || head === "entities") && name !== undefined) {
    return `${head}/${name}`;
  }
  return undefined;
}

/** True when the file starts with the "use client" directive. */
export function isClientModule(source: string): boolean {
  return /^\s*(?:\/\*[\s\S]*?\*\/\s*|\/\/[^\n]*\n\s*)*['"]use client['"]/.test(source);
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/[^\n]*$/gm, "");
}

/** Every static, side-effect, re-export and dynamic import specifier in the file. */
export function importRefs(source: string): ImportRef[] {
  const refs: ImportRef[] = [];
  const code = stripComments(source);
  const statement = /\b(import|export)\b(\s+type\b)?[^'";]*?\bfrom\s*['"]([^'"]+)['"]/g;
  for (const match of code.matchAll(statement)) {
    refs.push({ specifier: match[3] as string, typeOnly: match[2] !== undefined });
  }
  const bare = /\bimport\s*(\(\s*)?['"]([^'"]+)['"]/g;
  for (const match of code.matchAll(bare)) {
    refs.push({ specifier: match[2] as string, typeOnly: false });
  }
  return refs;
}

/** The src-relative path (without extension) an internal specifier points at, or null. */
export function resolveInternal(fromPath: string, specifier: string): string | null {
  let target: string;
  if (specifier.startsWith("@/")) {
    target = specifier.slice(2);
  } else if (specifier.startsWith("./") || specifier.startsWith("../")) {
    target = posix.normalize(posix.join(posix.dirname(fromPath), specifier));
  } else {
    return null;
  }
  return target.replace(CODE_EXTENSIONS, "");
}

/** True when `target` is the file's own directory or inside it. */
function withinOwnDirectory(fromPath: string, target: string): boolean {
  const dir = posix.dirname(fromPath);
  return dir === "." ? !target.includes("/") : target === dir || target.startsWith(`${dir}/`);
}

function checkExternal(file: SourceFile, layer: Layer, ref: ImportRef): Violation | null {
  const { specifier } = ref;
  const bare = specifier
    .split("/")
    .slice(0, specifier.startsWith("@") ? 2 : 1)
    .join("/");
  if (
    specifier === "@compliancewatch/contracts" ||
    specifier.startsWith("@compliancewatch/contracts/")
  ) {
    if (!ref.typeOnly) {
      return { file: file.path, specifier, reason: "contracts are imported type-only" };
    }
    return null;
  }
  if (layer === "shared" || layer === "entities") {
    if (SERVER_ONLY_MODULES.includes(specifier) || specifier.startsWith("node:")) {
      return { file: file.path, specifier, reason: `${layer} code is isomorphic` };
    }
  }
  if (
    layer === "entities" &&
    ENTITY_FORBIDDEN_PREFIXES.some((p) => bare === p || bare.startsWith(`${p}/`))
  ) {
    return {
      file: file.path,
      specifier,
      reason: "entities are pure: no React, next or UI imports",
    };
  }
  return null;
}

function checkInternal(
  file: SourceFile,
  layer: Layer,
  client: boolean,
  ref: ImportRef,
  target: string,
): Violation | null {
  const targetLayer = layerOf(target);
  const { specifier } = ref;
  if (!ALLOWED[layer].includes(targetLayer)) {
    return { file: file.path, specifier, reason: `${layer} must not import ${targetLayer}` };
  }
  const ownRoot = moduleRootOf(file.path);
  const targetRoot = moduleRootOf(target);
  if (layer === "features" && targetLayer === "features" && ownRoot !== targetRoot) {
    return { file: file.path, specifier, reason: "a feature must not import another feature" };
  }
  if (layer === "entities") {
    const sameEntity = targetLayer === "entities" && ownRoot === targetRoot;
    if (!sameEntity && !target.startsWith("shared/lib/")) {
      return {
        file: file.path,
        specifier,
        reason: "entities import shared/lib and themselves only",
      };
    }
  }
  if (
    client &&
    targetLayer !== "shared" &&
    targetLayer !== "entities" &&
    !withinOwnDirectory(file.path, target)
  ) {
    return {
      file: file.path,
      specifier,
      reason: "client components import shared, entities and their own directory only",
    };
  }
  return null;
}

export function checkFile(file: SourceFile): Violation[] {
  const layer = layerOf(file.path);
  if (layer === "test") return [];
  const client = isClientModule(file.source);
  const violations: Violation[] = [];
  if (layer === "server" && !/^\s*import\s+['"]server-only['"]/.test(stripComments(file.source))) {
    violations.push({
      file: file.path,
      specifier: "server-only",
      reason: 'server modules start with import "server-only"',
    });
  }
  for (const ref of importRefs(file.source)) {
    if (ASSET_EXTENSIONS.test(ref.specifier)) continue;
    const target = resolveInternal(file.path, ref.specifier);
    const violation =
      target === null
        ? checkExternal(file, layer, ref)
        : checkInternal(file, layer, client, ref, target);
    if (violation) violations.push(violation);
  }
  return violations;
}

export function checkTree(files: readonly SourceFile[]): Violation[] {
  return files.flatMap((file) => checkFile(file));
}
