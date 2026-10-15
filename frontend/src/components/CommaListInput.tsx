"use client";

import { useEffect, useState } from "react";

// "a, b,, c " -> ["a", "b", "c"]
export function parseCommaList(text: string): string[] {
  return text.split(",").map((s) => s.trim()).filter(Boolean);
}

type Props = {
  value: string[];
  onChange: (items: string[]) => void;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">;

/* An <input> for a comma-separated list. It keeps the text as typed and reports the parsed list.
   Re-joining the parsed list on every keystroke stripped a just-typed comma or trailing space,
   so a second item, or a name like "New York", could not be typed. */
export default function CommaListInput({ value, onChange, ...rest }: Props) {
  const [text, setText] = useState(value.join(", "));

  // Our own edits parse back to `value`; anything else (a load, a reset) replaces the text.
  useEffect(() => {
    if (parseCommaList(text).join("\n") !== value.join("\n")) setText(value.join(", "));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <input
      {...rest}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        onChange(parseCommaList(e.target.value));
      }}
    />
  );
}
