import ts from "typescript";

/**
 * The rule for the BFF route handlers, checked by handler-gate.test.ts over the real tree: the
 * proxy is left off `/api-bff/` (D-059), so a handler there is reached by nothing that checks the
 * session first, and each one must start with the shared gate (`server/bff/gate.ts`), given the
 * registry entry its route belongs to:
 *
 *   const SCREEN = screenById("system.uploads");
 *
 *   export async function POST(request: NextRequest, { params }: Context): Promise<Response> {
 *     const gate = await gateHandler(SCREEN, request);
 *     if (!gate.ok) return gate.response;
 *     ...
 *   }
 *
 * Every exported HTTP method is a function declaration whose first statement awaits the gate with
 * the handler's own request and the entry (a constant of `screenById(...)` or the call itself)
 * whose route is the file's, and whose second returns the refusal. Anything else, including an
 * HTTP method exported another way, is a problem that names the file.
 */
export interface RouteFile {
  /** Path relative to src, posix separators: `app/api-bff/.../route.ts`. */
  path: string;
  source: string;
}

export const HTTP_METHODS: readonly string[] = [
  "GET",
  "HEAD",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
  "OPTIONS",
];

const GATE_MODULE = "@/server/bff/gate";
const GATE = "gateHandler";
const REGISTRY_LOOKUP = "screenById";

/** The route a route file serves: its directories under app, route groups left out. */
export function routeOf(path: string): string {
  const segments = path
    .split("/")
    .slice(1, -1)
    .filter((segment) => !/^\(.*\)$/.test(segment));
  return `/${segments.join("/")}`;
}

function isExported(node: ts.Node): boolean {
  return (
    ts.canHaveModifiers(node) &&
    (ts.getModifiers(node) ?? []).some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword)
  );
}

/** The registry id a `screenById("...")` call names, or null for anything else. */
function lookedUpId(expression: ts.Expression): string | null {
  if (
    ts.isCallExpression(expression) &&
    ts.isIdentifier(expression.expression) &&
    expression.expression.text === REGISTRY_LOOKUP &&
    expression.arguments.length === 1
  ) {
    const [argument] = expression.arguments;
    if (argument !== undefined && ts.isStringLiteral(argument)) return argument.text;
  }
  return null;
}

/** The module's constants bound to a registry entry, by name. */
function entryConstants(file: ts.SourceFile): Map<string, string> {
  const constants = new Map<string, string>();
  for (const statement of file.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    if ((statement.declarationList.flags & ts.NodeFlags.Const) === 0) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || declaration.initializer === undefined) continue;
      const id = lookedUpId(declaration.initializer);
      if (id !== null) constants.set(declaration.name.text, id);
    }
  }
  return constants;
}

/** Whether the module imports the gate by its name from the gate's module. */
function importsGate(file: ts.SourceFile): boolean {
  return file.statements.some(
    (statement) =>
      ts.isImportDeclaration(statement) &&
      ts.isStringLiteral(statement.moduleSpecifier) &&
      statement.moduleSpecifier.text === GATE_MODULE &&
      statement.importClause?.isTypeOnly !== true &&
      statement.importClause?.namedBindings !== undefined &&
      ts.isNamedImports(statement.importClause.namedBindings) &&
      statement.importClause.namedBindings.elements.some(
        (element) =>
          !element.isTypeOnly && element.propertyName === undefined && element.name.text === GATE,
      ),
  );
}

/**
 * The gate's variable and the registry id it was given, when the statement is
 * `const <gate> = await gateHandler(<entry>, <request>)` with this handler's request.
 */
function gateCall(
  statement: ts.Statement | undefined,
  requestName: string,
  constants: ReadonlyMap<string, string>,
): { variable: string; id: string } | null {
  if (statement === undefined || !ts.isVariableStatement(statement)) return null;
  if ((statement.declarationList.flags & ts.NodeFlags.Const) === 0) return null;
  const [declaration, ...more] = statement.declarationList.declarations;
  if (declaration === undefined || more.length > 0 || !ts.isIdentifier(declaration.name)) {
    return null;
  }
  const awaited = declaration.initializer;
  if (awaited === undefined || !ts.isAwaitExpression(awaited)) return null;
  const callee = awaited.expression;
  if (!ts.isCallExpression(callee) || !ts.isIdentifier(callee.expression)) return null;
  if (callee.expression.text !== GATE || callee.arguments.length !== 2) return null;
  const [entry, request] = callee.arguments;
  if (entry === undefined || request === undefined) return null;
  if (!ts.isIdentifier(request) || request.text !== requestName) return null;
  const id = ts.isIdentifier(entry) ? (constants.get(entry.text) ?? null) : lookedUpId(entry);
  return id === null ? null : { variable: declaration.name.text, id };
}

/** Whether the statement is `if (!<gate>.ok) return <gate>.response;`. */
function returnsRefusal(statement: ts.Statement | undefined, variable: string): boolean {
  if (statement === undefined || !ts.isIfStatement(statement)) return false;
  if (statement.elseStatement !== undefined) return false;
  const test = statement.expression;
  const refused =
    ts.isPrefixUnaryExpression(test) &&
    test.operator === ts.SyntaxKind.ExclamationToken &&
    ts.isPropertyAccessExpression(test.operand) &&
    ts.isIdentifier(test.operand.expression) &&
    test.operand.expression.text === variable &&
    test.operand.name.text === "ok";
  if (!refused) return false;
  const then = ts.isBlock(statement.thenStatement)
    ? statement.thenStatement.statements.length === 1
      ? statement.thenStatement.statements[0]
      : undefined
    : statement.thenStatement;
  return (
    then !== undefined &&
    ts.isReturnStatement(then) &&
    then.expression !== undefined &&
    ts.isPropertyAccessExpression(then.expression) &&
    ts.isIdentifier(then.expression.expression) &&
    then.expression.expression.text === variable &&
    then.expression.name.text === "response"
  );
}

/** The names a statement exports, for an export that is not a function declaration. */
function otherExports(statement: ts.Statement): string[] {
  if (ts.isVariableStatement(statement) && isExported(statement)) {
    return statement.declarationList.declarations.flatMap((declaration) =>
      ts.isIdentifier(declaration.name) ? [declaration.name.text] : [],
    );
  }
  if (ts.isExportDeclaration(statement) && statement.exportClause !== undefined) {
    return ts.isNamedExports(statement.exportClause)
      ? statement.exportClause.elements.map((element) => element.name.text)
      : [];
  }
  return [];
}

/**
 * What is wrong with one route file under app/api-bff, one sentence each, naming the file.
 * `entryFor` gives the id of the registry's handler entry for a route, if one has it.
 */
export function handlerGateProblems(
  file: RouteFile,
  entryFor: (route: string) => string | undefined,
): string[] {
  const route = routeOf(file.path);
  const expected = entryFor(route);
  const problems: string[] = [];
  if (expected === undefined) {
    problems.push(`${file.path}: no handler entry of the screen registry has the route ${route}`);
  }
  const source = ts.createSourceFile(
    file.path,
    file.source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  );
  const constants = entryConstants(source);
  const gateImported = importsGate(source);
  let methods = 0;
  for (const statement of source.statements) {
    for (const name of otherExports(statement)) {
      if (!HTTP_METHODS.includes(name)) continue;
      methods += 1;
      problems.push(
        `${file.path}: ${name} must be exported as a function declaration that runs the gate first`,
      );
    }
    if (!ts.isFunctionDeclaration(statement) || !isExported(statement)) continue;
    const name = statement.name?.text ?? "";
    if (!HTTP_METHODS.includes(name)) continue;
    methods += 1;
    const [first] = statement.parameters;
    const requestName = first !== undefined && ts.isIdentifier(first.name) ? first.name.text : "";
    const body: readonly ts.Statement[] = statement.body?.statements ?? [];
    const gate = gateCall(body[0], requestName, constants);
    if (!gateImported || gate === null || !returnsRefusal(body[1], gate.variable)) {
      problems.push(
        `${file.path}: ${name} must start with \`const gate = await ${GATE}(SCREEN, ${requestName || "request"});\` ` +
          `and \`if (!gate.ok) return gate.response;\`, ${GATE} imported from ${GATE_MODULE}`,
      );
      continue;
    }
    if (expected !== undefined && gate.id !== expected) {
      problems.push(
        `${file.path}: ${name} gates with the entry ${gate.id}, but the route is ${expected}'s`,
      );
    }
  }
  if (methods === 0) problems.push(`${file.path}: exports no HTTP method`);
  return problems;
}
