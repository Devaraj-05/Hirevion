import { guardedPage, routeMetadata } from "@/page/guarded-page";
import { ProctoringReportsBody } from "@/reports/bodies";

export const generateMetadata = routeMetadata("/reports/proctoring");
export default guardedPage("/reports/proctoring", ProctoringReportsBody);
