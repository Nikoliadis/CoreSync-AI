/**
 * The official Google and Apple marks.
 *
 * Both are reproduced exactly — correct geometry, correct colours, no recolouring and no
 * redrawing. Each company's brand guidelines require that, and a hand-approximated mark
 * is the kind of thing that gets an app rejected at review rather than at design.
 *
 * The Google G keeps its four colours in both themes. It is never tinted to match the
 * page; the whole point of the mark is that it looks the same everywhere. The Apple mark
 * is monochrome by design and inherits `currentColor`, which is how Apple specifies it.
 */

export function GoogleMark({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden focusable="false">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

export function AppleMark({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 512 512"
      className={`${className} fill-current`}
      aria-hidden
      focusable="false"
    >
      <path d="M391.2 273.7c-.6-59.3 48.4-87.8 50.6-89.2-27.5-40.3-70.4-45.8-85.7-46.4-36.5-3.7-71.2 21.5-89.7 21.5-18.5 0-47-21-77.3-20.4-39.8.6-76.5 23.1-97 58.7-41.3 71.7-10.6 178 29.7 236.3 19.7 28.5 43.2 60.6 74.1 59.4 29.7-1.2 41-19.2 76.9-19.2s46 19.2 77.3 18.6c31.9-.6 52.1-29.1 71.6-57.7 22.5-33.1 31.8-65.1 32.4-66.7-.7-.3-62.2-23.9-62.9-94.9zM332.6 96.9c16.4-19.9 27.4-47.5 24.4-75.1-23.6.9-52.1 15.7-69 35.5-15.2 17.6-28.4 45.7-24.8 72.7 26.3 2 53.1-13.4 69.4-33.1z" />
    </svg>
  );
}
