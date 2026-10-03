import { ROUTES } from "./manifest";
import { can, type Session } from "./permissions";

/**
 * Where a session starts: the dashboard, or, when a custom role leaves it out, the first page in
 * the navigation the session may open. Everyone may open their own account page.
 */
export function homeFor(session: Session): string {
  return (
    ROUTES.find((route) => !route.detail && can(session, route.permission))?.path ?? "/account"
  );
}
