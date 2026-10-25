import type { ReactNode } from "react";

export type IconName =
  | "book"
  | "cap"
  | "compass"
  | "chat"
  | "activity"
  | "arrow"
  | "check"
  | "upload"
  | "pencil"
  | "calendar"
  | "school"
  | "user"
  | "chevron"
  | "home"
  | "clock"
  | "close";

const paths: Record<IconName, ReactNode> = {
  book: (
    <>
      <path d="M12 5.5C9 3.5 5 3.5 3 4v15c3-.7 6-.5 9 1 3-1.5 6-1.7 9-1V4c-2-.5-6-.5-9 1.5Z" />
      <path d="M12 5.5V20M6 8h3M6 11h3M15 8h3M15 11h3" />
    </>
  ),
  cap: (
    <>
      <path d="m2 9 10-5 10 5-10 5L2 9ZM6 11v6c3 3 9 3 12 0v-6M22 9v7" />
    </>
  ),
  compass: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m16 8-2 6-6 2 2-6 6-2Z" />
    </>
  ),
  chat: (
    <path d="M20 11a8 8 0 0 1-8 8H5l-3 3V11a9 9 0 0 1 18 0ZM7 9h8M7 13h5" />
  ),
  activity: (
    <>
      <path d="M3 12h4l3-7 4 14 3-7h4" />
    </>
  ),
  arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
  check: <path d="m5 12 4 4L19 6" />,
  upload: <path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5" />,
  pencil: (
    <>
      <path d="m15 4 5 5M4 20l2-7L17 2l5 5L11 18l-7 2ZM6 13l5 5" />
    </>
  ),
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M7 3v4M17 3v4M3 10h18M7 14h3M14 14h3M7 17h3" />
    </>
  ),
  school: (
    <>
      <path d="m2 9 10-6 10 6H2ZM4 9v10M9 9v10M15 9v10M20 9v10M2 21h20" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="3" />
      <path d="M5 21v-3a7 7 0 0 1 14 0v3" />
    </>
  ),
  chevron: <path d="m9 5 7 7-7 7" />,
  home: <path d="M3 11 12 4l9 7M5 9.5V20h5v-6h4v6h5V9.5" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6 6 18" />,
};

export function Icon({
  name,
  size = 20,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

export function StudySketch({
  variant = "books",
}: {
  variant?: "books" | "cap" | "pencil" | "compass";
}) {
  return (
    <svg
      className={`study-sketch sketch-${variant}`}
      viewBox="0 0 220 170"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {variant === "books" ? (
        <>
          <g transform="rotate(-7 110 95)">
            <path fill="var(--paper)" d="m46 111 99-9 35 17-101 12-33-20Z" />
            <path d="M46 111v15l33 20 101-12v-15M79 131v15M87 137l84-10" />
            <path fill="var(--paper)" d="m43 87 99-11 38 20-101 12-36-21Z" />
            <path d="M43 87v14l36 21 101-12V96M79 108v14M87 115l84-10" />
            <path fill="var(--paper)" d="m52 62 86-10 35 19-86 11-35-20Z" />
            <path d="M52 62v14l35 20 86-11V71M87 82v14M95 89l69-9" />
            <path d="m84 66 42-5M97 72l27-3" />
          </g>
          <g transform="rotate(26 172 50)">
            <path fill="var(--paper)" d="M167 19h10v55l-5 12-5-12V19Z" />
            <path d="M167 28h10M172 29v44M167 74h10" />
          </g>
          <path d="M29 57v10m-5-5h10M190 103v8m-4-4h8M121 25l3 5-3 5-3-5 3-5Z" />
          <path
            strokeDasharray="2 5"
            d="M25 140c-13-24-13-50 1-64M188 143c12-3 17-11 18-23"
          />
        </>
      ) : variant === "cap" ? (
        <>
          <g transform="rotate(-9 110 85)">
            <path fill="var(--paper)" d="m29 66 82-36 82 36-82 36-82-36Z" />
            <path d="M61 82v38c28 22 69 22 100 0V82M111 66l67 25v38M173 129l5-7 5 7v15h-10v-15Z" />
            <path d="m43 67 68-30 67 30M63 113c28 19 68 19 96 0" />
          </g>
          <path d="m28 121 4-8 4 8 8 4-8 4-4 8-4-8-8-4 8-4ZM179 26v10m-5-5h10M89 152h41" />
        </>
      ) : variant === "pencil" ? (
        <>
          <g transform="rotate(-9 105 90)">
            <rect
              x="48"
              y="35"
              width="104"
              height="109"
              rx="4"
              fill="var(--paper)"
            />
            <path d="M60 35v109M43 51h11M43 68h11M43 85h11M43 102h11M43 119h11M74 60h54M74 77h43M74 94h30" />
          </g>
          <g transform="rotate(31 158 80)">
            <path fill="var(--paper)" d="M151 23h13v99l-7 16-6-16V23Z" />
            <path d="M151 36h13M157 36v85M151 122h13" />
          </g>
          <path d="M25 45v10m-5-5h10M182 136v10m-5-5h10M170 12l2 4 4 2-4 2-2 4-2-4-4-2 4-2 2-4Z" />
        </>
      ) : (
        <>
          <circle cx="109" cy="85" r="52" fill="var(--paper)" />
          <circle cx="109" cy="85" r="44" />
          <path d="m131 62-13 32-32 13 13-32 32-13Z" />
          <path d="m99 75 19 19M109 46v8M109 117v8M70 85h8M140 85h8M103 27v-9h12v9" />
          <path
            strokeDasharray="3 5"
            d="M24 132c23 20 59 24 77 12M177 44c15 14 25 33 20 53"
          />
          <path d="M174 119v12m-6-6h12M40 48v8m-4-4h8" />
        </>
      )}
    </svg>
  );
}
