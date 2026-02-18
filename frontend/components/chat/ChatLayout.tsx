"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSWRConfig } from "swr";
import { createClient } from "@/lib/supabase";
import { Sidebar } from "./Sidebar";
import { ChatZone } from "./ChatZone";
import { cn } from "@/lib/utils";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const THREADS_KEY = "/api/chat/threads";
const LOG = "[FIRST-CHAT]";

export interface ThreadItem {
  thread_id: string;
  title: string | null;
  created_at: string;
}

export function ChatLayout() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const threadIdFromUrl = searchParams.get("threadId") ?? null;
  const { mutate } = useSWRConfig();
  const [activeThreadIdOverride, setActiveThreadIdOverride] = useState<string | null>(null);

  // When URL catches up with the new thread (e.g. after refresh), clear the override
  useEffect(() => {
    if (threadIdFromUrl && threadIdFromUrl === activeThreadIdOverride) {
      setActiveThreadIdOverride(null);
    }
  }, [threadIdFromUrl, activeThreadIdOverride]);

  const currentThreadId = threadIdFromUrl ?? activeThreadIdOverride ?? null;

  const onDeleteThread = useCallback(
    async (threadId: string) => {
      const {
        data: { session },
      } = await createClient().auth.getSession();
      if (!session?.access_token) return;
      const res = await fetch(`${BACKEND_URL}/api/chat/threads/${threadId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${session.access_token}` },
        credentials: "include",
      });
      if (!res.ok) return;
      setActiveThreadIdOverride(null);
      mutate(THREADS_KEY);
      if (threadIdFromUrl === threadId) router.push("/");
    },
    [threadIdFromUrl, router, mutate]
  );

  const onThreadCreated = useCallback((threadId: string) => {
    setActiveThreadIdOverride(threadId);
  }, []);

  return (
    <div className={cn("flex h-screen bg-zinc-950")}>
      <Sidebar currentThreadId={currentThreadId} onDeleteThread={onDeleteThread} />
      <ChatZone
        threadId={threadIdFromUrl}
        onThreadCreated={onThreadCreated}
      />
    </div>
  );
}
