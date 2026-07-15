import { useEffect, useRef } from "react";

export function ScrollTabs({
  value,
  options,
  ariaLabel,
  className = "",
  onChange
}: {
  value: string;
  options: readonly string[];
  ariaLabel: string;
  className?: string;
  onChange: (value: string) => void;
}) {
  const activeRef = useRef<HTMLButtonElement | null>(null);
  const keyboardNavigationRef = useRef(false);

  useEffect(() => {
    activeRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
      inline: "nearest"
    });
    if (keyboardNavigationRef.current) {
      activeRef.current?.focus();
      keyboardNavigationRef.current = false;
    }
  }, [value]);

  function moveFocus(currentIndex: number, direction: "next" | "previous" | "first" | "last") {
    const lastIndex = options.length - 1;
    const nextIndex = direction === "first"
      ? 0
      : direction === "last"
        ? lastIndex
        : direction === "next"
          ? (currentIndex + 1) % options.length
          : (currentIndex - 1 + options.length) % options.length;
    keyboardNavigationRef.current = true;
    onChange(options[nextIndex]);
  }

  return (
    <div className={`scroll-tabs ${className}`.trim()} role="tablist" aria-label={ariaLabel}>
      {options.map((item, index) => (
        <button
          key={item}
          ref={value === item ? activeRef : undefined}
          type="button"
          role="tab"
          title={item}
          tabIndex={value === item ? 0 : -1}
          aria-selected={value === item}
          className={`scroll-tab ${value === item ? "active" : ""}`}
          onClick={() => onChange(item)}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight") {
              event.preventDefault();
              moveFocus(index, "next");
            } else if (event.key === "ArrowLeft") {
              event.preventDefault();
              moveFocus(index, "previous");
            } else if (event.key === "Home") {
              event.preventDefault();
              moveFocus(index, "first");
            } else if (event.key === "End") {
              event.preventDefault();
              moveFocus(index, "last");
            }
          }}
        >
          {item}
        </button>
      ))}
    </div>
  );
}
