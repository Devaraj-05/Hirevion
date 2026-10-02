import { PlatformOrganizationsBody } from "@/admin/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/platform/organizations");
export default guardedPage("/platform/organizations", PlatformOrganizationsBody);
