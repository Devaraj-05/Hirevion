import { RolesBody } from "@/admin/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin/roles");
export default guardedPage("/admin/roles", RolesBody);
