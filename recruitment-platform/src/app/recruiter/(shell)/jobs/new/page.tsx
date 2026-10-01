import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/jobs/new");
export default guardedPage("/jobs/new");
