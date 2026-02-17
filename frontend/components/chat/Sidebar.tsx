"use client";

import Link from "next/link";
import { MessageSquarePlus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { ThreadItem } from "./ChatLayout";
import { cn } from "@/lib/utils";

interface SidebarProps {
  threads: ThreadItem[];
  currentThreadId: string | null;
  loading: boolean;
  onRefresh: () => void;
}

export function Sidebar({
  threads,
  currentThreadId,
  loading,
  onRefresh,
}: SidebarProps) {
  return (
    <aside className="flex w-64 flex-col border-r border-zinc-800 bg-zinc-900/50">
      <div className="flex items-center justify-between border-b border-zinc-800 p-3">
        <span className="text-sm font-medium text-zinc-300">Conversations</span>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={onRefresh}
            disabled={loading}
            className="h-8 w-8"
            title="Rafraîchir"
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Link href="/" title="Nouvelle conversation">
            <Button variant="ghost" size="icon" className="h-8 w-8">
              <MessageSquarePlus className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      </div>
      <ScrollArea className="flex-1">
        <div className="space-y-0.5 p-2">
          <Link
            href="/"
            className={cn(
              "block rounded-md px-3 py-2 text-sm transition-colors",
              !currentThreadId
                ? "bg-zinc-700 text-zinc-100"
                : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            )}
          >
            Nouvelle conversation
          </Link>
          {loading && threads.length === 0 ? (
            <p className="px-3 py-2 text-sm text-zinc-500">Chargement…</p>
          ) : (
            threads.map((thread) => {
              const isActive = currentThreadId === thread.thread_id;
              return (
                <Link
                  key={thread.thread_id}
                  href={`/?threadId=${thread.thread_id}`}
                  className={cn(
                    "block rounded-md px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-zinc-700 text-zinc-100"
                      : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                  )}
                >
                  {thread.title || "Sans titre"}
                </Link>
              );
            })
          )}
        </div>
      </ScrollArea>
    </aside>
  );
}
