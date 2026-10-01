import { SectionIndexBody } from "@/page/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin");
export default guardedPage("/admin", SectionIndexBody);
