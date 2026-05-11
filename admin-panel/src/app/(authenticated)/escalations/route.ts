import { type NextRequest } from "next/server";

/**
 * 308 Permanent Redirect: /escalations → /conversations?filter=escalated
 *
 * The standalone Escalaciones page has been merged into the Conversaciones inbox
 * as a filter tab. This route handler ensures all existing links and bookmarks
 * are permanently redirected without losing the escalated-filter context.
 *
 * FR-MIGRATE-1, SC-5.
 */
export function GET(request: NextRequest) {
  const destination = new URL("/conversations?filter=escalated", request.url);
  return Response.redirect(destination, 308);
}
