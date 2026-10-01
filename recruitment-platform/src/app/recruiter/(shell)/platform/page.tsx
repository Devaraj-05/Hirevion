import { SectionIndexBody } from "@/page/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/platform");
export default guardedPage("/platform", SectionIndexBody);
