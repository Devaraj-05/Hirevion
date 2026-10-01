import {
  Bell,
  BookOpen,
  Briefcase,
  ChartColumn,
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
  admin: Settings,
  platform: ShieldCheck,
};
