import { guardedPage, routeMetadata } from "@/page/guarded-page";
import { CandidateReportsBody } from "@/reports/bodies";

export const generateMetadata = routeMetadata("/reports/candidate");
export default guardedPage("/reports/candidate", CandidateReportsBody);
