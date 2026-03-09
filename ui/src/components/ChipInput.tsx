"use client";

import { useState, KeyboardEvent } from "react";

interface ChipInputProps {
  label: string;
  value: string[];
  onChange: (tags: string[]) => void;
  max?: number;
}

export default function ChipInput({ label, value, onChange, max = 10 }: ChipInputProps) {
  const [input, setInput] = useState("");

  const addTag = (raw: string) => {
    const tag = raw.trim().toLowerCase().replace(/\s+/g, "_");
    if (!tag || value.includes(tag) || value.length >= max) return;
    onChange([...value, tag]);
    setInput("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(input);
    }
  };

  const removeTag = (tag: string) => {
    onChange(value.filter((t) => t !== tag));
  };

  return (
    <div>
      <label className="text-xs font-medium text-gray-500">{label}</label>
      <div className="flex flex-wrap gap-1 mt-1 mb-1">
        {value.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 bg-blue-100 text-blue-800 text-xs px-2 py-0.5 rounded"
          >
            {tag}
            <button onClick={() => removeTag(tag)} className="hover:text-red-600">&times;</button>
          </span>
        ))}
      </div>
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={value.length >= max ? `Max ${max} tags` : "Add tag..."}
        disabled={value.length >= max}
        className="border rounded px-2 py-1 text-sm w-full"
      />
    </div>
  );
}
