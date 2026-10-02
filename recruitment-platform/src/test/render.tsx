import { TooltipProvider } from "@hirevion/ui";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement, ReactNode } from "react";
import { StepUpProvider } from "@/admin/step-up";
import messages from "../../messages/en-IN.json";

function IntlProviders({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider locale="en-IN" messages={messages} timeZone="Asia/Kolkata">
      <TooltipProvider>{children}</TooltipProvider>
    </NextIntlClientProvider>
  );
}

/** Renders with the en-IN catalogue and the providers the app's root layout supplies. */
export function renderWithIntl(ui: ReactElement) {
  return render(<IntlProviders>{ui}</IntlProviders>);
}

/** Also the shell's query client (no retries, so failures show at once) and step-up. */
export function renderAdmin(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <IntlProviders>
      <QueryClientProvider client={client}>
        <StepUpProvider>{ui}</StepUpProvider>
      </QueryClientProvider>
    </IntlProviders>,
  );
}
