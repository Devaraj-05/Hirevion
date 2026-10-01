import { JobsBody } from "@/page/feature-bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/jobs");
export default guardedPage("/jobs", JobsBody);
