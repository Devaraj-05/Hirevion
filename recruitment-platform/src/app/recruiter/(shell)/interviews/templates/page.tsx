import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/interviews/templates");
export default guardedPage("/interviews/templates");
