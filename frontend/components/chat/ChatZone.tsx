"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useChat } from "ai/react";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MessageList, HITL_MARKER } from "./MessageList";
import { ApprovalRequest } from "./ApprovalRequest";
import { cn } from "@/lib/utils";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const CHAT_API = `${BACKEND_URL}/api/chat`;

interface ChatZoneProps {
  threadId: string | null;
  onThreadCreated: () => void;
}

export function ChatZone({ threadId, onThreadCreated }: ChatZoneProps) {
  const router = useRouter();
  const supabase = createClient();
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const lastThreadIdRef = useRef<string | null>(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }: { data: { session: { access_token?: string } | null } }) => {
      setSessionToken(session?.access_token ?? null);
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event: string, session: { access_token?: string } | null) => {
      setSessionToken(session?.access_token ?? null);
    });
    return () => subscription.unsubscribe();
  }, [supabase.auth]);

  const {
    messages,
    setMessages,
    input,
    setInput,
    handleSubmit,
    isLoading,
    reload,
  } = useChat({
    api: CHAT_API,
    streamProtocol: "text",
    body: { thread_id: threadId ?? undefined },
    headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : undefined,
    credentials: "include",
    onResponse: (res) => {
      const threadIdHeader = res.headers.get("X-Thread-Id");
      if (threadIdHeader && !threadId) {
        lastThreadIdRef.current = threadIdHeader;
      }
    },
    onFinish: () => {
      if (lastThreadIdRef.current) {
        router.replace(`/?threadId=${lastThreadIdRef.current}`);
        onThreadCreated();
        lastThreadIdRef.current = null;
      }
    },
  });

  // Load thread history when opening an existing thread (or on reload)
  const historyLoadedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!threadId || !sessionToken) return;
    let cancelled = false;
    fetch(`${BACKEND_URL}/api/chat/history?thread_id=${encodeURIComponent(threadId)}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      credentials: "include",
    })
      .then((res) => (res.ok ? res.json() : { messages: [] }))
      .then((data: { messages?: Array<{ role: string; content: string }> }) => {
        if (cancelled || !data.messages?.length) return;
        // Only inject history once per thread so we don't overwrite new messages
        if (historyLoadedRef.current === threadId) return;
        historyLoadedRef.current = threadId;
        const withIds = data.messages.map((m, i) => ({
          id: `hist-${threadId}-${i}`,
          role: m.role as "user" | "assistant" | "system",
          content: m.content ?? "",
        }));
        setMessages(withIds);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [threadId, sessionToken, setMessages]);

  const lastAssistantMessage = messages.filter((m) => m.role === "assistant").pop();
  const showApproval = Boolean(
    lastAssistantMessage && "content" in lastAssistantMessage && typeof lastAssistantMessage.content === "string" && lastAssistantMessage.content.includes(HITL_MARKER)
  );

  const handleApprove = useCallback(async () => {
    if (!threadId && lastThreadIdRef.current) {
      router.replace(`/?threadId=${lastThreadIdRef.current}`);
    }
    const tid = threadId ?? lastThreadIdRef.current;
    if (!tid || !sessionToken) return;
    try {
      const res = await fetch(`${BACKEND_URL}/api/chat/resume`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${sessionToken}`,
        },
        body: JSON.stringify({ thread_id: tid, action: "approve" }),
      });
      if (res.ok) reload();
    } catch {
      // ignore
    }
  }, [threadId, sessionToken, router, reload]);

  const handleReject = useCallback(async () => {
    const tid = threadId ?? lastThreadIdRef.current;
    if (!tid || !sessionToken) return;
    try {
      await fetch(`${BACKEND_URL}/api/chat/resume`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${sessionToken}`,
        },
        body: JSON.stringify({ thread_id: tid, action: "reject" }),
      });
      reload();
    } catch {
      // ignore
    }
  }, [threadId, sessionToken, reload]);

  const handleFormSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!input.trim() || !sessionToken) return;
    handleSubmit(e);
  };

  return (
    <div className="flex flex-1 flex-col bg-zinc-950">
      <div className="flex-1 overflow-y-auto">
        <MessageList messages={messages} isLoading={isLoading} />
      </div>

      {showApproval && (
        <ApprovalRequest
          onApprove={handleApprove}
          onReject={handleReject}
          loading={isLoading}
        />
      )}

      <form
        onSubmit={handleFormSubmit}
        className="border-t border-zinc-800 bg-zinc-900/50 p-4"
      >
        <div className="mx-auto flex max-w-3xl gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Écrivez votre message…"
            disabled={isLoading}
            className="flex-1"
          />
          <Button type="submit" disabled={isLoading || !sessionToken}>
            Envoyer
          </Button>
        </div>
      </form>
    </div>
  );
}
