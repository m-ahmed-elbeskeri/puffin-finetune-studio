// AUTO-GENERATED. Pixelarticons glyphs wrapped as Phosphor-compatible React
// components. One local module so every `@phosphor-icons/react` import can be
// repointed here with no call-site changes. Regenerate: see scripts/gen-icons (mapping in git log).
"use client";
import * as React from "react";

export interface IconProps extends Omit<React.SVGProps<SVGSVGElement>, "ref"> {
  size?: number | string;
  /** Accepted for Phosphor API parity; ignored (pixel glyphs have a single weight). */
  weight?: string;
  strokeWidth?: number | string;
  mirrored?: boolean;
}

const G: Record<string, string> = {
  "analytics": "<path d=\"M4 2h16v2H4zm0 18h16v2H4zM2 4h2v16H2zm18 0h2v16h-2zm-9 8h2v6h-2zm-4 2h2v4H7zm8-8h2v12h-2z\"/>",
  "arrow-big-up": "<path d=\"M8 21h8v-2H8zm0-2h2v-6H8zm-5-6h5v-2H3zm0-2h2V9H3zm2-2h2V7H5zm2-2h2V5H7zm2-2h2V3H9zm2-2h2V1h-2zm2 2h2V3h-2zm2 2h2V5h-2zm2 2h2V7h-2zm2 4h2V9h-2zm-3 0h3v-2h-3zm-2 6h2v-6h-2z\"/>",
  "arrow-right": "<path d=\"M4 11v2h16v-2zm12 2v2h2v-2zm-2 2v2h2v-2zm-2 2v2h2v-2zm4-6V9h2v2z\"/> <path d=\"M14 15V7h2v8zm-2 2V5h2v12z\"/>",
  "arrow-up": "<path d=\"M11 20h2V4h-2zm2-12h2V6h-2zm2 2h2V8h-2zm2 2h2v-2h-2zm-6-4H9V6h2z\"/> <path d=\"M15 10H7V8h8zm2 2H5v-2h12z\"/>",
  "blocks": "<path d=\"M15 1h6v2h-6zm-2 2h2v6h-2zm2 6h6v2h-6zm6-6h2v6h-2zM3 5h6v2H3zM1 7h2v14H1zm2 14h14v2H3zm14-6h2v6h-2zM3 13h14v2H3z\"/> <path d=\"M9 7h2v14H9z\"/>",
  "book-open": "<path d=\"M2 3h9v2H2zM0 19h11v2H0zM13 3h9v2h-9zm0 16h11v2H13zM11 5h2v18h-2zM0 5h2v14H0zm22 0h2v14h-2zm-7 2h5v2h-5zm0 4h5v2h-5zm0 4h2v2h-2z\"/>",
  "box": "<path d=\"M14 4h4v2h-4zm-4-2h4v2h-4zM6 8h4v2H6zm0 10h4v2H6zm4-8h4v2h-4zm0 10h4v2h-4zm4-12h4v2h-4zm0 10h4v2h-4zM6 4h4v2H6zM2 6h4v2H2zm0 10h4v2H2zM18 6h4v2h-4zm0 10h4v2h-4z\"/> <path d=\"M2 6h2v12H2zm18 0h2v12h-2zm-8 6h2v8h-2z\"/>",
  "braces": "<path d=\"M6 4h4v2H6zm12 0h-4v2h4zM6 20h4v-2H6zm12 0h-4v-2h4zM4 6h2v5H4zm16 0h-2v5h2zM4 18h2v-5H4zm16 0h-2v-5h2zM2 11h2v2H2zm20 0h-2v2h2z\"/>",
  "cancel": "<path d=\"M6 2h12v2H6zm0 18h12v2H6zM2 6h2v12H2zm18 0h2v12h-2zm-2-2h2v2h-2zm-2 2h2v2h-2zm-2 2h2v2h-2zm-2 2h2v2h-2zm-2 2h2v2h-2zm-2 2h2v2H8zm-2 2h2v2H6zm12 2h2v2h-2zM4 4h2v2H4zm0 14h2v2H4z\"/>",
  "chart": "<path d=\"M4 2h16v2H4zm0 18h16v2H4zM2 4h2v16H2zm18 0h2v16h-2zM7 11h2v6H7zm4-4h2v10h-2zm4 6h2v4h-2z\"/>",
  "check": "<path d=\"M10 18H8v-2h2v2Zm-2-2H6v-2h2v2Zm4-2v2h-2v-2h2Zm-6 0H4v-2h2v2Zm8 0h-2v-2h2v2Zm2-2h-2v-2h2v2Zm2-2h-2V8h2v2Zm2-2h-2V6h2v2Z\"/>",
  "check-double": "<path d=\"M7 18H5v-2h2v2Zm6 0h-2v-2h2v2Zm-8-2H3v-2h2v2Zm4 0H7v-2h2v2Zm6-2v2h-2v-2h2ZM3 14H1v-2h2v2Zm8 0H9v-2h2v2Zm6 0h-2v-2h2v2Zm-4-2h-2v-2h2v2Zm6 0h-2v-2h2v2Zm-4-2h-2V8h2v2Zm6 0h-2V8h2v2Zm-4-2h-2V6h2v2Zm6 0h-2V6h2v2Z\"/>",
  "chevron-down": "<path d=\"M13 16h-2v-2h2v2Zm-2-2H9v-2h2v2Zm4 0h-2v-2h2v2Zm-6-2H7v-2h2v2Zm8 0h-2v-2h2v2ZM7 10H5V8h2v2Zm12 0h-2V8h2v2Z\"/>",
  "chevron-left": "<path d=\"M8 13v-2h2v2H8Zm2-2V9h2v2h-2Zm0 4v-2h2v2h-2Zm2-6V7h2v2h-2Zm0 8v-2h2v2h-2Zm2-10V5h2v2h-2Zm0 12v-2h2v2h-2Z\"/>",
  "chevron-right": "<path d=\"M16 13v-2h-2v2h2Zm-2-2V9h-2v2h2Zm0 4v-2h-2v2h2Zm-2-6V7h-2v2h2Zm0 8v-2h-2v2h2ZM10 7V5H8v2h2Zm0 12v-2H8v2h2Z\"/>",
  "clipboard": "<path d=\"M4 6h2v14H4zm2 14h12v2H6zM18 6h2v14h-2zM6 4h2v2H6zm10 0h2v2h-2zm-6-2h4v2h-4zm0 4h4v2h-4zM8 2h2v6H8zm6 0h2v6h-2z\"/>",
  "clock": "<path d=\"M6 2h12v2H6zM2 6h2v12H2zm18 0h2v12h-2zm-2-2h2v2h-2zM4 4h2v2H4zm2 18h12v-2H6zm12-2h2v-2h-2zM4 20h2v-2H4zm7-14h2v7h-2zm2 7h2v2h-2zm2 2h2v2h-2z\"/>",
  "close": "<path d=\"M7 19H5V17H7V19ZM19 19H17V17H19V19ZM9 15V17H7V15H9ZM17 17H15V15H17V17ZM11 15H9V13H11V15ZM15 15H13V13H15V15ZM13 13H11V11H13V13ZM11 11H9V9H11V11ZM15 11H13V9H15V11ZM9 9H7V7H9V9ZM17 9H15V7H17V9ZM7 7H5V5H7V7ZM19 7H17V5H19V7Z\"/>",
  "cloud": "<path d=\"M22 10h-4v2h4v-2Zm2 2h-2v6h2v-6Zm-2 6H2v2h20v-2ZM2 12H0v6h2v-6Zm2-2H2v2h2v-2Zm4-2H4v2h4V8Zm8-4h-6v2h6V4Zm-6 2H8v2h2V6Zm0 4H8v2h2v-2Zm8-4h-2v2h2V6Z\"/> <path d=\"M20 8h-2v4h2V8Zm-2 4h-2v2h2v-2Z\"/>",
  "copy": "<path d=\"M8 6h12v2H8zM4 2h12v2H4zm2 6h2v12H6zM2 4h2v12H2zm6 16h12v2H8zM20 8h2v12h-2zm-4-4h2v2h-2zM4 16h2v2H4z\"/>",
  "cpu": "<path d=\"M5 3h14v2H5zm0 16h14v2H5zM3 5h2v14H3zm16 0h2v14h-2zM9 7h6v2H9zm0 8h6v2H9zM7 9h2v6H7zm8 0h2v6h-2zm-4-8h2v2h-2zm0 20h2v2h-2zM1 11h2v2H1zm20 0h2v2h-2zm0-4h2v2h-2zm0 8h2v2h-2zM1 15h2v2H1zm0-8h2v2H1zm6-6h2v2H7zm8 0h2v2h-2zm0 20h2v2h-2zm-8 0h2v2H7z\"/>",
  "database": "<path d=\"M2 6h2v4H2zm0 4h2v4H2zm0 4h2v4H2zm18-8h2v4h-2zm0 4h2v4h-2zm0 4h2v4h-2zM4 4h4v2H4zm0 8h4v-2H4zm0 4h4v-2H4zm0 4h4v-2H4zM16 4h4v2h-4zm0 8h4v-2h-4zm0 4h4v-2h-4zm0 4h4v-2h-4zM8 2h8v2H8zm0 12h8v-2H8zm0 4h8v-2H8zm0 4h8v-2H8z\"/>",
  "delete": "<path d=\"M6 7h2v2H6zm14 0h2v10h-2zM8 5h12v2H8zM4 9h2v2H4zm-2 2h2v2H2zm2 2h2v2H4zm2 2h2v2H6zm2 2h12v2H8zm6-6h2v2h-2zm2 2h2v2h-2zm0-4h2v2h-2zm-4 4h2v2h-2zm0-4h2v2h-2z\"/>",
  "directions": "<path d=\"M2 2h2v2H2zm2 2h2v2H4zm2-2h2v2H6zM2 6h2v2H2zm4 0h2v2H6zm11 9h3v2h-3zm-2 2h2v3h-2zm2 3h3v2h-3zm3-3h2v3h-2zM15 2h2v10h-2zm-2 2h2v2h-2z\"/> <path d=\"M11 6h9v2h-9z\"/> <path d=\"M19 6h2v2h-2zm-2-2h2v2h-2zM6 12h9v2H6zm-2 2h2v4H4zm0 6h2v2H4z\"/>",
  "download": "<path d=\"M21 15v4h-2v-4zm-2 4v2H5v-2zM5 15v4H3v-4zm8-12v14h-2V3z\"/> <path d=\"M7 11v2h10v-2zm2 2v2h2v-2zm4 0v2h2v-2z\"/> <path d=\"M15 11v2h2v-2z\"/>",
  "external-link": "<path d=\"M11 5H5v2h6V5ZM5 7H3v12h2V7Zm12 12H5v2h12v-2Zm2-6h-2v6h2v-6Zm-8 0H9v2h2v-2Zm2-2h-2v2h2v-2Zm2-2h-2v2h2V9Zm2-2h-2v2h2V7Zm2-2h-2v2h2V5Zm2-2h-2v8h2V3Z\"/> <path d=\"M21 3h-8v2h8V3Z\"/>",
  "eye": "<path d=\"M16 20H8v-2h8v2Zm-8-2H4v-2h4v2Zm12 0h-4v-2h4v2ZM4 16H2v-2h2v2Zm10-6h-2v2h2v-2h2v4h-2v2h-4v-2H8v-4h2V8h4v2Zm8 6h-2v-2h2v2ZM2 14H0v-4h2v4Zm22 0h-2v-4h2v4ZM4 10H2V8h2v2Zm18 0h-2V8h2v2ZM8 8H4V6h4v2Zm12 0h-4V6h4v2Zm-4-2H8V4h8v2Z\"/>",
  "eye-off": "<path d=\"M0 10h2v4H0zm24 0h-2v4h2zm-8 0h-2v2h2zm-6 0H8v4h2zM2 8h2v2H2zm0 8h2v-2H2zm20-8h-2v2h2zm0 8h-2v-2h2zM4 6h4v2H4zm0 12h4v-2H4zM20 6h-4v2h4zM10 4h6v2h-6zM8 20h8v-2H8zm4-12h2v2h-2zm-2 6h4v2h-4zM8 8h2v2H8zm2 2h2v4h-2zm2 2h2v2h-2z\"/> <path d=\"M6 6h2v2H6zM4 4h2v2H4zM2 2h2v2H2zm12 12h2v2h-2zm2 2h2v2h-2zm2 2h2v2h-2zm2 2h2v2h-2z\"/>",
  "file-text": "<path d=\"M6 4H4v16h2zm10-2H6v2h10zm4 4h-2v14h2zm-2 14H6v2h12zM16 4h2v2h-2zm-4 0h2v6h-2z\"/> <path d=\"M12 8h6v2h-6zm-4 8h8v2H8zm0-4h8v2H8zm0-4h2v2H8z\"/>",
  "files": "<path d=\"M9 3H7v14h2zM5 7H3v14h2zm12-6H9v2h8zm4 4h-2v12h2zm-2 12H9v2h10zm-4 4H5v2h10zm2-18h2v2h-2zm-4 0h2v6h-2z\"/> <path d=\"M13 7h6v2h-6zM5 5h2v2H5zm10 14h2v2h-2z\"/>",
  "filter": "<path d=\"M11 20H13V22H9V12H11V20ZM15 20H13V12H15V20ZM9 12H7V10H9V12ZM17 12H15V10H17V12ZM7 10H5V8H7V10ZM19 10H17V8H19V10ZM21 8H19V4H5V8H3V2H21V8Z\"/>",
  "fire": "<path d=\"M9 2h2v4H9zM7 6h2v2H7zM5 8h2v2H5zm8 2h2v2h-2zm2-2h2v2h-2zm2 2h2v2h-2zm2 2h2v6h-2zM3 10h2v8H3zm8-4h2v4h-2zm6 12h2v2h-2zM7 20h10v2H7zm-2-2h2v2H5zm4-2h6v4H9z\"/> <path d=\"M11 14h2v3h-2z\"/>",
  "folder": "<path d=\"M4 4h6v2H4zm0 14h16v2H4zM20 8h2v10h-2zM2 6h2v12H2zm8 0h10v2H10z\"/>",
  "grid-3x3": "<path d=\"M4 2h16v2H4zm0 18h16v2H4zM2 4h2v16H2zm18 0h2v16h-2zM4 8h16v2H4zm0 6h16v2H4z\"/> <path d=\"M8 4h2v16H8zm6 0h2v16h-2z\"/>",
  "hash": "<path d=\"M9 3h2v5H9zm6 0h2v5h-2zm-7 7h2v4H8zm6 0h2v4h-2zm-7 6h2v5H7zm6 0h2v5h-2zM3 8h18v2H3zm0 6h18v2H3z\"/>",
  "info-box": "<path d=\"M4 2h16v2H4zm0 18h16v2H4zM2 4h2v16H2zm18 0h2v16h-2zm-9 5h2V7h-2zm0 8h2v-6h-2z\"/>",
  "lightbulb": "<path d=\"M9 4h6v2H9zM7 6h2v2H7zm8 0h2v2h-2zm4-2h2v2h-2zm2-2h2v2h-2zM0 10h3v2H0zm21 0h3v2h-3zM3 4h2v2H3zM1 2h2v2H1zm6 12h2v2H7zm8 0h2v2h-2zM5 8h2v6H5zm12 0h2v6h-2zm-8 8h6v2H9zm0 4h6v2H9zm0-2h2v2H9zm4 0h2v2h-2zM11 0h2v3h-2z\"/>",
  "list-box": "<path d=\"M4 2h16v2H4zm2 5h2v2H6zm4 0h8v2h-8zm-4 4h2v2H6zm4 0h8v2h-8zm-4 4h2v2H6zm4 0h8v2h-8zm-6 5h16v2H4zM2 4h2v16H2zm18 0h2v16h-2z\"/>",
  "loader": "<path d=\"M13 22h-2v-6h2v6Zm-6-3H5v-2h2v2Zm12 0h-2v-2h2v2ZM9 17H7v-2h2v2Zm8 0h-2v-2h2v2Zm-9-4H2v-2h6v2Zm14 0h-6v-2h6v2ZM9 9H7V7h2v2Zm8 0h-2V7h2v2Zm-4-1h-2V2h2v6ZM7 7H5V5h2v2Zm12 0h-2V5h2v2Z\"/>",
  "lock": "<path d=\"M5 8h14v2H5zm0 12h14v2H5zM3 10h2v10H3zm16 0h2v10h-2zM7 4h2v4H7zm2-2h6v2H9zm6 2h2v4h-2z\"/>",
  "magic-edit": "<path d=\"M16 2h4v2h-4zm2 2h2v2h-2zm-2 2h2v2h-2zm-2 2h2v2h-2zm-2 2h2v2h-2zm-2 2h2v2h-2zm-2 2h2v2H8zm-2 2h2v2H6zm-2 2h2v2H4zm-2-2h2v4H2zm2-2h2v2H4zm2-2h2v2H6zm2-2h2v2H8zm2-2h2v2h-2zm2-2h2v2h-2zm2-2h2v2h-2zm0 2h2v2h-2zm2-2h2v2h-2zm0 8h2v2h-2zm0 8h2v2h-2zm-4-4h2v2h-2zm8 0h2v2h-2zm-6-2h2v2h-2zm4 0h2v2h-2zm0 4h2v2h-2zm-4 0h2v2h-2zM4 2h2v2H4zM2 4h2v2H2zm2 2h2v2H4zm2-2h2v2H6zm14 6h2v2h-2zM8 20h2v2H8z\"/>",
  "message": "<path d=\"M20 2H4v2h16zm0 14H6v2h14zm2-12h-2v12h2zM4 4H2v18h2zm2 14H4v2h2z\"/>",
  "moon": "<path d=\"M18 22H8v-2h10v2ZM8 20H6v-2h2v2Zm12 0h-2v-2h2v2ZM6 18H4v-2h2v2Zm16 0h-2v-4h-2v-2h2v-2h2v8ZM4 16H2V6h2v10Zm14 0h-6v-2h6v2Zm-6-2h-2v-2h2v2Zm-2-2H8V6h2v6ZM6 6H4V4h2v2Zm8-2h-2v2h-2V4H6V2h8v2Z\"/>",
  "more-horizontal": "<path d=\"M3 9h2v2H3zm8 0h2v2h-2zm8 0h2v2h-2zM1 11h2v2H1zm8 0h2v2H9zm8 0h2v2h-2zM3 13h2v2H3zm8 0h2v2h-2zm8 0h2v2h-2zM5 11h2v2H5zm8 0h2v2h-2zm8 0h2v2h-2z\"/>",
  "more-vertical": "<path d=\"M15 3v2h-2V3zm0 8v2h-2v-2zm0 8v2h-2v-2zM13 1v2h-2V1zm0 8v2h-2V9zm0 8v2h-2v-2zM11 3v2H9V3zm0 8v2H9v-2zm0 8v2H9v-2zm2-14v2h-2V5zm0 8v2h-2v-2zm0 8v2h-2v-2z\"/>",
  "package": "<path d=\"M10 20h4v2h-4zm0-16h4V2h-4zm0 6h4v2h-4zm4 8h4v2h-4zm0-12h4V4h-4zm0 2h4v2h-4zm4 8h4v2h-4zm0-8h4V6h-4zM6 18h4v2H6zM6 6h4V4H6zm0 2h4v2H6zm-4 8h4v2H2zm0-8h4V6H2z\"/> <path d=\"M2 6h2v12H2zm18 0h2v12h-2zm-8 6h2v8h-2zm-2-6h4v2h-4z\"/>",
  "pencil": "<path d=\"M4 16H6V18H8V20H10V22H2V14H4V16ZM12 20H10V18H12V20ZM14 18H12V16H14V18ZM10 16H8V14H10V16ZM16 16H14V14H16V16ZM6 14H4V12H6V14ZM12 14H10V12H12V14ZM18 14H16V12H18V14ZM8 12H6V10H8V12ZM14 12H12V10H14V12ZM20 12H18V10H20V12ZM10 10H8V8H10V10ZM18 10H16V8H18V10ZM22 10H20V8H22V10ZM12 8H10V6H12V8ZM16 8H14V6H16V8ZM20 8H18V6H20V8ZM14 6H12V4H14V6ZM18 6H16V4H18V6ZM16 4H14V2H16V4Z\" fill=\"black\"/>",
  "play": "<path d=\"M15 11h-2V9h2zm0 4h-2v-2h2zm-2 2h-2v-2h2zm0-8h-2V7h2zm-2-2H9V5h2zM9 21H7V3h2zm6-8h2v-2h-2zm-6 4h2v2H9z\"/>",
  "plus": "<path d=\"M13 11h7v2h-7v7h-2v-7H4v-2h7V4h2v7Z\"/>",
  "plus-box": "<path d=\"M4 2h16v2H4zm0 18h16v2H4zM2 4h2v16H2zm18 0h2v16h-2zM7 11h10v2H7z\"/> <path d=\"M11 17V7h2v10z\"/>",
  "reload": "<path d=\"M16 4h2v6h-2zm-2-2h2v2h-2zm0 2h2v8h-2zM4 8H2v5h2z\"/> <path d=\"M4 6h16v2H4zm4 14H6v-6h2zm2 2H8v-2h2zm0-2H8v-8h2zm10-4h2v-5h-2z\"/> <path d=\"M20 18H4v-2h16z\"/>",
  "save": "<path d=\"M20 22H4V20H6V14H8V20H16V14H18V20H20V22ZM4 20H2V4H4V20ZM22 20H20V6H22V20ZM16 14H8V12H16V14ZM12 10H6V6H12V10ZM20 6H18V4H20V6ZM18 4H4V2H18V4Z\"/>",
  "scale": "<path d=\"M13 9h2v2h-2zm2-2h2v2h-2zm2-2h2v2h-2zm2-2h2v8h-2z\"/> <path d=\"M13 3h8v2h-8zm-2 12H9v-2h2zm-2 2H7v-2h2zm-2 2H5v-2h2zm-2 2H3v-8h2z\"/> <path d=\"M11 21H3v-2h8z\"/>",
  "scan-barcode": "<path d=\"M16 2h4v2h-4zm4 2h2v4h-2zm0 12h2v4h-2zm-4 4h4v2h-4zM4 20h4v2H4zm-2-4h2v4H2zM2 4h2v4H2zm2-2h4v2H4zm3 6h2v8H7zm4 0h2v8h-2zm5 0h2v8h-2z\"/>",
  "scissors": "<path d=\"M5 2h4v2H5zm0 12h4v2H5zm0-6h4v2H5zm0 12h4v2H5zM3 4h2v4H3zm0 12h2v4H3zM9 4h2v4H9zm0 12h2v4H9zm0-8h2v2H9zm2 2h2v2h-2zm-2 4h2v2H9zm2-2h2v2h-2zm2-2h2v2h-2zm2 4h2v2h-2zm2 2h2v2h-2zm2 2h2v2h-2zM15 8h2v2h-2zm2-2h2v2h-2zm2-2h2v2h-2z\"/>",
  "script": "<path d=\"M16 19h2v2H4v-2h10v-2h2v2ZM6 15h8v2H4v2H2v-4h2V5h2v10ZM20 5h2v6h-2v8h-2V5H6V3h14v2Z\"/>",
  "scroll-vertical": "<path d=\"M21 8h-2V4h2zM5 8H3V4h2zm16 6h-2v-4h2zM5 14H3v-4h2zm16 6h-2v-4h2zM5 20H3v-4h2zm10-2H9v2h6z\"/> <path d=\"M13 2h-2v20h2z\"/> <path d=\"M17 16H7v2h10zM15 6H9V4h6zm2 2H7V6h10z\"/>",
  "search": "<path d=\"M22 22h-2v-2h2v2Zm-2-2h-2v-2h2v2Zm-6-2H6v-2h8v2Zm4 0h-2v-2h2v2ZM6 16H4v-2h2v2Zm10 0h-2v-2h2v2ZM4 14H2V6h2v8Zm14 0h-2V6h2v8ZM6 6H4V4h2v2Zm10 0h-2V4h2v2Zm-2-2H6V2h8v2Z\"/>",
  "send": "<path d=\"M4 19h4v2H2v-8h2v6Zm8 0H8v-2h4v2Zm4-2h-4v-2h4v2Zm4-2h-4v-2h4v2Zm-10-2H4v-2h6v2Zm12 0h-2v-2h2v2ZM8 5H4v6H2V3h6v2Zm12 6h-4V9h4v2Zm-4-2h-4V7h4v2Zm-4-2H8V5h4v2Z\"/>",
  "server": "<path d=\"M6 7h4v2H6zm0 8h4v2H6zM2 5h2v14H2zm18 0h2v14h-2zM4 19h16v2H4zM4 3h16v2H4zm0 8h16v2H4z\"/>",
  "settings-2": "<path d=\"M4 14h2v6H4zm6 0h2v6h-2zm-4-2h4v2H6zm0 8h4v2H6zm-4-4h2v2H2zm20-8h-4V6h4z\"/> <path d=\"M10 16h12v2H10zm4-8H2V6h12zm6-4v2h-2V4zm0 6V8h-2v2zm-6-8h4v2h-4zm0 10h4v-2h-4zm-2-8h2v2h-2zm0 6h2V8h-2z\"/>",
  "settings-cog": "<g clip-path=\"url(#a)\"> <path d=\"M9 0h6v2H9zm6 24H9v-2h6zM0 15V9h2v6zm24-6v6h-2V9zM9 2h2v4H9zm6 20h-2v-4h2zM2 15v-2h4v2zm20-6v2h-4V9zm-9-7h2v4h-2zm-2 20H9v-4h2zM2 11V9h4v2zm20 2v2h-4v-2zM7 4h2v2H7zm10 0h-2v2h2zm0 16h-2v-2h2zM7 20h2v-2H7zM2 2h5v2H2zm20 0h-5v2h5zm0 20h-5v-2h5zM2 22h5v-2H2z\"/> <path d=\"M2 2h2v5H2zm20 0h-2v5h2zm0 20h-2v-5h2zM2 22h2v-5H2zM4 7h2v2H4zm16 0h-2v2h2zm0 10h-2v-2h2zM4 17h2v-2H4zm6-9h4v2h-4zm0 6h4v2h-4zm-2-4h2v4H8zm6 0h2v4h-2z\"/> </g> <defs> <clipPath id=\"a\"> <path fill=\"#fff\" d=\"M0 0h24v24H0z\"/> </clipPath> </defs>",
  "shield": "<path d=\"M4 2h16v2H4zM2 4h2v10H2zm18 0h2v10h-2zM4 14h2v2H4zm2 2h2v2H6zm4 4h4v2h-4zm10-6h-2v2h2zm-2 2h-2v2h2zm-2 2h-2v2h2zm-6 0H8v2h2z\"/>",
  "shuffle": "<path d=\"M10 19H2v-2h8v2Zm12 0h-8v-2h8v2Zm-10-2h-2v-6h2v6Zm6-10h2v2h2v2h-2v2h-2v2h-2v-4h-4V9h4V5h2v2ZM8 11H2V9h6v2Z\"/>",
  "signal": "<path d=\"M19 3h2v18h-2zm-4 4h2v14h-2zm-4 4h2v10h-2zm-4 4h2v6H7zm-4 4h2v2H3z\"/>",
  "sort-vertical": "<path d=\"M16 4h2v16h-2zm-2 10h2v4h-2zm-2 0h2v2h-2zm6 0h2v4h-2zm2 0h2v2h-2zM6 20h2V4H6zM4 10h2V6H4zm-2 0h2V8H2zm6 0h2V6H8zm2 0h2V8h-2z\"/>",
  "sparkle": "<path d=\"M11 1h2v4h-2zm0 22h2v-4h-2zM9 5h2v4H9zm0 14h2v-4H9zm4-14h2v4h-2zm0 14h2v-4h-2zM5 9h4v2H5zm14 0h-4v2h4zM1 11h4v2H1zm22 0h-4v2h4zM5 13h4v2H5zm14 0h-4v2h4z\"/>",
  "sparkles": "<path d=\"M11 1h2v4h-2zm0 22h2v-4h-2zM9 5h2v4H9zm0 14h2v-4H9zm4-14h2v4h-2zm0 14h2v-4h-2zM5 9h4v2H5zm14 0h-4v2h4zM1 11h4v2H1zm22 0h-4v2h4zM5 13h4v2H5zm14 0h-4v2h4zm0-12h2v6h-2z\"/> <path d=\"M17 3h6v2h-6zM3 17h2v2H3zm-2 2h2v2H1zm2 2h2v2H3zm2-2h2v2H5z\"/>",
  "speed-medium": "<path d=\"M5 19H3v-2h2v2Zm16 0h-2v-2h2v2ZM3 17H1v-6h2v6Zm11 0h-4v-4h1V5h2v8h1v4Zm9 0h-2v-6h2v6ZM5 11H3V9h2v2Zm16 0h-2V9h2v2ZM9 9H5V7h4v2Zm10 0h-4V7h4v2Z\"/>",
  "square": "<path d=\"M2 4h2v16H2zm2 16h16v2H4zM20 4h2v16h-2zM4 2h16v2H4z\"/>",
  "square-alert": "<path d=\"M4 2h16v2H4zm0 18h16v2H4zM20 4h2v16h-2zM2 4h2v16H2zm9 2h2v8h-2zm0 10h2v2h-2z\"/>",
  "terminal": "<path d=\"M4 2h16v2H4zm0 18h16v2H4zM2 4h2v16H2zm18 0h2v16h-2zM6 16h2v2H6zm2-2h2v2H8zm-2-2h2v2H6z\"/>",
  "test-tube": "<path d=\"M7 2h10v2H7zm1 2h2v16H8zm2 16h4v2h-4zm4-16h2v16h-2z\"/> <path d=\"M8 13h8v2H8z\"/>",
  "tool-case": "<path d=\"M2 11h20v2H2zm0 2h2v8H2zm2 8h16v2H4zm16-8h2v8h-2zM9 15h6v2H9zM4 8h2v3H4zm2-2h6v2H6zm6 2h2v3h-2zM8 4h2v2H8zm10 0h2v7h-2zm-8-2h8v2h-8z\"/>",
  "trash": "<path d=\"M18 22H6V20H18V22ZM9 6H15V4H17V6H22V8H20V20H18V8H6V20H4V8H2V6H7V4H9V6ZM15 4H9V2H15V4Z\"/>",
  "undo": "<path d=\"M18 20h-6v-2h6v2Zm2-2h-2v-8h2v8Zm-10-4H8v-2H6v-2H4V8h2V6h2V4h2v4h8v2h-8v4Z\"/>",
  "upload": "<path d=\"M19 21H5v-2h14v2ZM5 19H3v-4h2v4Zm16 0h-2v-4h2v4ZM13 5h2v2h2v2h-4v8h-2V9H7V7h2V5h2V3h2v2Z\"/>",
  "user": "<path d=\"M9 2h6v2H9zm0 8h6v2H9zm6-6h2v6h-2zM7 4h2v6H7zM4 18h2v4H4zm14 0h2v4h-2zM8 14h8v2H8zm-2 2h2v2H6zm10 0h2v2h-2z\"/>",
  "warning-diamond": "<path d=\"M2 10h2v2H2zm0 4h2v-2H2zm20-4h-2v2h2zm0 4h-2v-2h2zM4 8h2v2H4zm0 8h2v-2H4zm16-8h-2v2h2zm0 8h-2v-2h2zM6 6h2v2H6zm0 12h2v-2H6zM18 6h-2v2h2zm0 12h-2v-2h2zM8 4h2v2H8zm0 16h2v-2H8zm8-16h-2v2h2zm0 16h-2v-2h2zM10 2h2v2h-2zm0 20h2v-2h-2zm4-20h-2v2h2zm0 20h-2v-2h2zm-3-5h2v-2h-2zm0-4h2V7h-2z\"/>",
  "zap": "<path d=\"M4 13h8v6h2v2h-2v2h-2v-8H2v-4h2v2Zm12 6h-2v-2h2v2Zm2-2h-2v-2h2v2Zm2-2h-2v-2h2v2Zm-6-6h8v4h-2v-2h-8V5h-2V3h2V1h2v8Zm-8 2H4V9h2v2Zm2-2H6V7h2v2Zm2-2H8V5h2v2Z\"/>",
  "zoom-in": "<path d=\"M22 22h-2v-2h2v2Zm-2-2h-2v-2h2v2Zm-6-2H6v-2h8v2Zm4 0h-2v-2h2v2ZM6 16H4v-2h2v2Zm10 0h-2v-2h2v2ZM4 14H2V6h2v8Zm7-5h3v2h-3v3H9v-3H6V9h3V6h2v3Zm7 5h-2V6h2v8ZM6 6H4V4h2v2Zm10 0h-2V4h2v2Zm-2-2H6V2h8v2Z\"/>",
};

function make(key: string, name: string) {
  const Icon = React.forwardRef<SVGSVGElement, IconProps>(function Icon(
    { size = 16, weight, strokeWidth, mirrored, width, height, ...rest }, ref,
  ) {
    const s = size ?? width ?? height ?? 16;
    return (
      <svg
        ref={ref}
        viewBox="0 0 24 24"
        width={s}
        height={s}
        fill="currentColor"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden={rest["aria-label"] ? undefined : true}
        {...rest}
        dangerouslySetInnerHTML={{ __html: G[key] }}
      />
    );
  });
  Icon.displayName = name;
  return Icon;
}

export const Activity = make("analytics", "Activity");
export const AlertCircle = make("square-alert", "AlertCircle");
export const AlertTriangle = make("warning-diamond", "AlertTriangle");
export const ArrowRight = make("arrow-right", "ArrowRight");
export const ArrowUp = make("arrow-up", "ArrowUp");
export const BadgeCheck = make("check-double", "BadgeCheck");
export const BookOpen = make("book-open", "BookOpen");
export const Boxes = make("blocks", "Boxes");
export const Braces = make("braces", "Braces");
export const CaretLeft = make("chevron-left", "CaretLeft");
export const CaretRight = make("chevron-right", "CaretRight");
export const Check = make("check", "Check");
export const CheckCircle2 = make("check-double", "CheckCircle2");
export const ChevronDown = make("chevron-down", "ChevronDown");
export const ChevronLeft = make("chevron-left", "ChevronLeft");
export const ChevronRight = make("chevron-right", "ChevronRight");
export const CircleSlash = make("cancel", "CircleSlash");
export const ClipboardPaste = make("clipboard", "ClipboardPaste");
export const Clock = make("clock", "Clock");
export const Clock3 = make("clock", "Clock3");
export const Cloud = make("cloud", "Cloud");
export const Compass = make("directions", "Compass");
export const Container = make("box", "Container");
export const Copy = make("copy", "Copy");
export const Cpu = make("cpu", "Cpu");
export const Database = make("database", "Database");
export const Download = make("download", "Download");
export const Eraser = make("delete", "Eraser");
export const ExternalLink = make("external-link", "ExternalLink");
export const Eye = make("eye", "Eye");
export const EyeOff = make("eye-off", "EyeOff");
export const FileCode2 = make("script", "FileCode2");
export const FileDown = make("download", "FileDown");
export const FileJson = make("braces", "FileJson");
export const FilePlus2 = make("plus-box", "FilePlus2");
export const FileText = make("file-text", "FileText");
export const Filter = make("filter", "Filter");
export const Fingerprint = make("scan-barcode", "Fingerprint");
export const Flame = make("fire", "Flame");
export const FlaskConical = make("test-tube", "FlaskConical");
export const FolderOpen = make("folder", "FolderOpen");
export const Gauge = make("speed-medium", "Gauge");
export const GripVertical = make("more-vertical", "GripVertical");
export const Hash = make("hash", "Hash");
export const HelpCircle = make("info-box", "HelpCircle");
export const History = make("reload", "History");
export const KeyRound = make("lock", "KeyRound");
export const Layers = make("files", "Layers");
export const LayoutDashboard = make("grid-3x3", "LayoutDashboard");
export const LayoutTemplate = make("list-box", "LayoutTemplate");
export const LineChart = make("chart", "LineChart");
export const List = make("list-box", "List");
export const ListOrdered = make("sort-vertical", "ListOrdered");
export const Loader2 = make("loader", "Loader2");
export const Lock = make("lock", "Lock");
export const MessageSquare = make("message", "MessageSquare");
export const Moon = make("moon", "Moon");
export const MoreHorizontal = make("more-horizontal", "MoreHorizontal");
export const Package = make("package", "Package");
export const PackageCheck = make("package", "PackageCheck");
export const PenLine = make("pencil", "PenLine");
export const Pencil = make("pencil", "Pencil");
export const Play = make("play", "Play");
export const PlayCircle = make("play", "PlayCircle");
export const Plus = make("plus", "Plus");
export const Radio = make("signal", "Radio");
export const RefreshCw = make("reload", "RefreshCw");
export const Rocket = make("arrow-big-up", "Rocket");
export const RotateCcw = make("undo", "RotateCcw");
export const Save = make("save", "Save");
export const Scale = make("scale", "Scale");
export const ScanSearch = make("zoom-in", "ScanSearch");
export const Scissors = make("scissors", "Scissors");
export const ScrollText = make("scroll-vertical", "ScrollText");
export const Search = make("search", "Search");
export const Send = make("send", "Send");
export const Server = make("server", "Server");
export const ServerCrash = make("warning-diamond", "ServerCrash");
export const Settings = make("settings-2", "Settings");
export const Settings2 = make("settings-cog", "Settings2");
export const ShieldAlert = make("shield", "ShieldAlert");
export const ShieldCheck = make("shield", "ShieldCheck");
export const Shuffle = make("shuffle", "Shuffle");
export const Sliders = make("settings-2", "Sliders");
export const Sparkle = make("sparkle", "Sparkle");
export const Sparkles = make("sparkles", "Sparkles");
export const Square = make("square", "Square");
export const Sun = make("lightbulb", "Sun");
export const Table2 = make("grid-3x3", "Table2");
export const Terminal = make("terminal", "Terminal");
export const Trash2 = make("trash", "Trash2");
export const Upload = make("upload", "Upload");
export const User = make("user", "User");
export const Wand2 = make("magic-edit", "Wand2");
export const Wrench = make("tool-case", "Wrench");
export const X = make("close", "X");
export const XCircle = make("cancel", "XCircle");
export const Zap = make("zap", "Zap");
