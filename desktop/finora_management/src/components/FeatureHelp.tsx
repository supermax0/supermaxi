import { useId, useRef, useState } from "react";
import { Popover } from "./Popover";

/** Click and keyboard accessible help, also works on touch screens. */
export function FeatureHelp({ text, label = "شرح الميزة" }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const anchor = useRef<HTMLButtonElement>(null);
  return (
    <span className="relative inline-flex align-middle">
      <button
        ref={anchor}
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
        className="grid h-6 w-6 place-items-center rounded-full bg-violet-soft text-xs font-bold text-violet-deep ring-1 ring-violet/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet"
      >
        ?
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={label} width={280}>
        {open && (
          <span id={id} role="note" className="block p-3 text-start text-xs font-normal leading-6 text-ink">
            {text}
          </span>
        )}
      </Popover>
    </span>
  );
}
