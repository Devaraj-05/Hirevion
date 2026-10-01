import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/jobs/new");
export default guardedPage("/jobs/new");
