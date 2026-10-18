import { guardedPage, routeMetadata } from "@/page/guarded-page";
import { PendingReviewsBody } from "@/reports/bodies";

export const generateMetadata = routeMetadata("/reports/pending");
export default guardedPage("/reports/pending", PendingReviewsBody);
