"use client";

import { useState } from "react";

interface Props {
  onSend: (content: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatComposer({ onSend, disabled, placeholder }: Props) {
  const [value, setValue] = useState("");

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!value.trim() || disabled) return;

    onSend(value);
    setValue("");
  }

  return (
    <form
      onSubmit={submit}
      className="border-t border-black/10 p-4 dark:border-white/15"
    >
      <div className="flex gap-2">
        <input
          type="text"
          name="question"
          value={value}
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          placeholder={placeholder ?? "Ask a question about your documents"}
          className="flex-1 rounded-md border border-black/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 disabled:opacity-50 dark:border-white/20 dark:focus:border-white/50"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </form>
  );
}
