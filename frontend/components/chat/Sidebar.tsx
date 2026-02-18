"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { Loader2, MessageSquarePlus, RefreshCw, Trash2 } from "lucide-react";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { ThreadItem } from "./ChatLayout";
import { cn } from "@/lib/utils";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const THREADS_KEY = "/api/chat/threads";

const fetcher = async (url: string): Promise<ThreadItem[]> => {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session?.access_token) return [];
  const res = await fetch(`${BACKEND_URL}${url}`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
    credentials: "include",
  });
  if (!res.ok) return [];
  return res.json();
};

interface SidebarProps {
  currentThreadId: string | null;
  onDeleteThread: (threadId: string) => void;
}

export function Sidebar({ currentThreadId, onDeleteThread }: SidebarProps) {
  const [sessionReady, setSessionReady] = useState(false);
  useEffect(() => {
    createClient()
      .auth.getSession()
      .then(({ data: { session } }) => {
        setSessionReady(!!session);
      });
    const {
      data: { subscription },
    } = createClient().auth.onAuthStateChange((_event, session) => {
      setSessionReady(!!session);
    });
    return () => subscription.unsubscribe();
  }, []);

  const { data: threads = [], mutate, isLoading } = useSWR<ThreadItem[]>(
    sessionReady ? THREADS_KEY : null,
    fetcher
  );

  return (
    <aside className="flex w-64 flex-col border-r border-zinc-800 bg-zinc-900/50">
      <div className="flex items-center justify-between border-b border-zinc-800 p-3">
        <span className="text-sm font-medium text-zinc-300">Conversations</span>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => mutate()}
            disabled={isLoading}
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
          {isLoading && threads.length === 0 ? (
            <p className="px-3 py-2 text-sm text-zinc-500">Chargement…</p>
          ) : (
            threads.map((thread) => {
              const isActive = currentThreadId === thread.thread_id;
              return (
                <div
                  key={thread.thread_id}
                  className={cn(
                    "group flex items-center gap-1 rounded-md pr-1 transition-colors",
                    isActive
                      ? "bg-zinc-700 text-zinc-100"
                      : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                  )}
                >
                  <Link
                    href={`/?threadId=${thread.thread_id}`}
                    className={cn(
                      "flex min-w-0 flex-1 items-center gap-1.5 px-3 py-2 text-sm",
                      isActive ? "text-zinc-100" : "text-zinc-400 hover:text-zinc-200"
                    )}
                  >
                    {(thread.title === null ||
                      thread.title === "" ||
                      thread.title === "New Chat" ||
                      thread.title === "Nouveau chat...") ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                        <span className="truncate">Génération…</span>
                      </>
                    ) : (
                      <span className="block truncate">{thread.title}</span>
                    )}
                  </Link>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0 opacity-70 hover:opacity-100 hover:text-red-400"
                    title="Supprimer la conversation"
                    onClick={(e) => {
                      e.preventDefault();
                      onDeleteThread(thread.thread_id);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              );
            })
          )}
        </div>
      </ScrollArea>
    </aside>
  );
}
