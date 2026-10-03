import { CandidatesBody } from "@/candidates/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/candidates");
export default guardedPage("/candidates", CandidatesBody);
