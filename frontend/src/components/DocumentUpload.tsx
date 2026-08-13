"use client";

import { useRef, useState } from "react";

import { ALLOWED_EXTENSIONS, MAX_UPLOAD_MB } from "@/lib/validation";

interface Props {
  onFilesSelected: (files: File[]) => void;
  onTextSubmit: (text: string) => void;
  disabled?: boolean;
}

export function DocumentUpload({ onFilesSelected, onTextSubmit, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [showTextInput, setShowTextInput] = useState(false);
  const [text, setText] = useState("");

  function handleDrop(event: React.DragEvent) {
    event.preventDefault();
    setIsDragging(false);

    if (disabled) return;

    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) {
      onFilesSelected(files);
    }
  }

  function handleBrowse(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (files.length > 0) {
      onFilesSelected(files);
    }
    // Reset so selecting the same file twice still fires a change event.
    event.target.value = "";
  }

  function handleTextSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;

    onTextSubmit(text);
    setText("");
    setShowTextInput(false);
  }

  return (
    <section className="space-y-3">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
          isDragging
            ? "border-blue-500 bg-blue-500/10"
            : "border-black/15 dark:border-white/20"
        } ${disabled ? "opacity-50" : ""}`}
      >
        <p className="text-sm font-medium">Drag and drop a document here</p>
        <p className="mt-1 text-xs opacity-60">
          {ALLOWED_EXTENSIONS.join(", ")} &middot; up to {MAX_UPLOAD_MB}MB
        </p>

        <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
          <button
            type="button"
            disabled={disabled}
            onClick={() => inputRef.current?.click()}
            className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            Browse files
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => setShowTextInput((open) => !open)}
            className="rounded-md border border-black/15 px-3 py-1.5 text-sm transition-opacity hover:opacity-70 disabled:opacity-50 dark:border-white/20"
          >
            {showTextInput ? "Cancel" : "Paste text"}
          </button>
        </div>

        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ALLOWED_EXTENSIONS.join(",")}
          onChange={handleBrowse}
          className="hidden"
          data-testid="file-input"
        />
      </div>

      {showTextInput && (
        <form onSubmit={handleTextSubmit} className="space-y-2">
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={6}
            placeholder="Paste or type the text you want to ask questions about."
            className="w-full rounded-md border border-black/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:border-white/20 dark:focus:border-white/50"
          />
          <button
            type="submit"
            disabled={disabled || !text.trim()}
            className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            Add text document
          </button>
        </form>
      )}
    </section>
  );
}
