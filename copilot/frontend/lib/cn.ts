/**
 * Conditional className helper. Used everywhere: wraps clsx + tailwind-merge
 * so duplicate utility classes are deduped (e.g. p-2 + p-4 -> p-4).
 */
import clsx, { type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
