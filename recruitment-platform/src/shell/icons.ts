import {
  Bell,
  BookOpen,
  Briefcase,
  ChartColumn,
  CircleUser,
  LayoutDashboard,
  type LucideIcon,
  Settings,
  ShieldCheck,
  Users,
  Video,
} from "lucide-react";
import type { Section } from "@/auth/manifest";

export const SECTION_ICONS: Record<Section, LucideIcon> = {
  dashboard: LayoutDashboard,
  jobs: Briefcase,
  candidates: Users,
  interviews: Video,
  questions: BookOpen,
  reports: ChartColumn,
  notifications: Bell,
  account: CircleUser,
  admin: Settings,
  platform: ShieldCheck,
};
