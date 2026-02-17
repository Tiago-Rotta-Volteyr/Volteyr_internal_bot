"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { Sidebar } from "./Sidebar";
import { ChatZone } from "./ChatZone";
import { cn } from "@/lib/utils";

export interface ThreadItem {
  thread_id: string;
  title: string | null;
  created_at: string;
}

export function ChatLayout() {
  const searchParams = useSearchParams();
  const threadIdFromUrl = searchParams.get("threadId") ?? null;
  const [threads, setThreads] = useState<ThreadItem[]>([]);
  const [loadingThreads, setLoadingThreads] = useState(true);
  const supabase = createClient();

  const fetchThreads = useCallback(async () => {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session) return;
    const { data, error } = await supabase
      .from("threads")
      .select("thread_id, title, created_at")
      .order("created_at", { ascending: false });
    if (!error) setThreads((data as ThreadItem[]) ?? []);
    setLoadingThreads(false);
  }, [supabase]);

  useEffect(() => {
    fetchThreads();
  }, [fetchThreads]);

  const currentThreadId = threadIdFromUrl ?? null;

  const onThreadCreated = useCallback(() => {
    fetchThreads();
  }, [fetchThreads]);

  return (
    <div className={cn("flex h-screen bg-zinc-950")}>
      <Sidebar
        threads={threads}
        currentThreadId={currentThreadId}
        loading={loadingThreads}
        onRefresh={fetchThreads}
      />
      <ChatZone
        key={currentThreadId ?? "new"}
        threadId={currentThreadId}
        onThreadCreated={onThreadCreated}
      />
    </div>
  );
}
