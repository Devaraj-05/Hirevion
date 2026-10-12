import { CandidateRequestsBody } from "@/candidates/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/candidates/requests");
export default guardedPage("/candidates/requests", CandidateRequestsBody);
