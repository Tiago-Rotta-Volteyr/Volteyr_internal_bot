"use client";

import ReactMarkdown from "react-markdown";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

export const HITL_MARKER = "[[VOLTEYR_HITL]]";

function stripHitlMarker(text: string): string {
  return text.replace(new RegExp(HITL_MARKER.replace(/\[/g, "\\["), "g"), "").trim();
}

export interface Message {
  id: string;
  role: "system" | "user" | "assistant";
  content: string;
}

/** Accepts AI SDK messages (role may include "tool" | "function" | "data"); only user/assistant are rendered. */
interface MessageListProps {
  messages: Array<{ id: string; role: string; content?: string }>;
  isLoading?: boolean;
}

function getMessageContent(msg: { content?: string }): string {
  return typeof msg.content === "string" ? msg.content : "";
}

export function MessageList({ messages, isLoading }: MessageListProps) {
  const displayMessages = messages.filter(
    (m) => m.role === "user" || m.role === "assistant"
  ) as Array<{ id: string; role: "user" | "assistant"; content?: string }>;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4">
      {displayMessages.length === 0 && !isLoading && (
        <p className="text-center text-sm text-zinc-500">
          Commencez une conversation ou choisissez un fil existant.
        </p>
      )}
      {displayMessages.map((msg) => (
        <div
          key={msg.id}
          className={cn(
            "flex gap-3",
            msg.role === "user" ? "justify-end" : "justify-start"
          )}
        >
          {msg.role !== "user" && (
            <Avatar className="h-8 w-8 shrink-0 rounded-full bg-zinc-700">
              <AvatarFallback className="text-xs text-zinc-300">AI</AvatarFallback>
            </Avatar>
          )}
          <div
            className={cn(
              "rounded-lg px-4 py-2 text-sm",
              msg.role === "user"
                ? "bg-zinc-700 text-zinc-100"
                : "bg-zinc-800/80 text-zinc-200"
            )}
          >
            {msg.role === "assistant" ? (
              <div className="prose prose-invert prose-sm max-w-none break-words">
                <ReactMarkdown>{stripHitlMarker(getMessageContent(msg))}</ReactMarkdown>
              </div>
            ) : (
              <span className="whitespace-pre-wrap">{getMessageContent(msg)}</span>
            )}
          </div>
          {msg.role === "user" && (
            <Avatar className="h-8 w-8 shrink-0 rounded-full bg-zinc-600">
              <AvatarFallback className="text-xs text-zinc-200">U</AvatarFallback>
            </Avatar>
          )}
        </div>
      ))}
      {isLoading && displayMessages[displayMessages.length - 1]?.role === "user" && (
        <div className="flex gap-3">
          <Avatar className="h-8 w-8 shrink-0 rounded-full bg-zinc-700">
            <AvatarFallback className="text-xs text-zinc-300">AI</AvatarFallback>
          </Avatar>
          <div className="rounded-lg bg-zinc-800/80 px-4 py-2 text-sm text-zinc-400">
            Réflexion…
          </div>
        </div>
      )}
    </div>
  );
}
