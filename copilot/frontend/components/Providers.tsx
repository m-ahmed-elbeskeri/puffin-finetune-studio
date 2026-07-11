"use client";
/**
 * App-wide data defaults. A shared SWR config so navigating between pages
 * reuses cached data (instant revisits) and stops the refetch storms that made
 * switching feel laggy: no revalidate-on-focus, deduped requests, and previous
 * data kept visible while the next page's data loads.
 */
import * as React from "react";
import { SWRConfig } from "swr";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        revalidateOnFocus: false,
        keepPreviousData: true,
        dedupingInterval: 4_000,
        focusThrottleInterval: 10_000,
        errorRetryCount: 2,
      }}
    >
      {children}
    </SWRConfig>
  );
}
