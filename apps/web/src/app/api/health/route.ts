import { NextResponse } from "next/server";

/**
 * Liveness for the stack wait script and Playwright's web server check. Version comes from
 * the package manager's environment when the app is started through a pnpm script; the commit
 * is whatever the deployment sets in CW_WEB_BUILD_SHA.
 */
export function GET() {
  return NextResponse.json({
    status: "ok",
    version: process.env.npm_package_version ?? "unknown",
    commit: process.env.CW_WEB_BUILD_SHA ?? "dev",
  });
}
