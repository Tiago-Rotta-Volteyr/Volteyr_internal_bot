"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useChat } from "ai/react";
import { useSWRConfig } from "swr";
import { v4 as uuidv4 } from "uuid";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MessageList, HITL_MARKER } from "./MessageList";
import { ApprovalRequest } from "./ApprovalRequest";
import { cn } from "@/lib/utils";
import type { ThreadItem } from "./ChatLayout";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const CHAT_API = `${BACKEND_URL}/api/chat`;

const THREADS_KEY = "/api/chat/threads";
const TEMP_TITLE = "Nouveau chat...";
const FLOW = "[FLOW]";

interface ChatZoneProps {
  threadId: string | null;
  onThreadCreated?: (threadId: string) => void;
}

export function ChatZone({ threadId, onThreadCreated }: ChatZoneProps) {
  const { mutate } = useSWRConfig();
  const supabase = createClient();
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const pendingThreadIdRef = useRef<string | null>(null);
  const threadIdRef = useRef<string | null>(threadId);
  threadIdRef.current = threadId;

  // ID figé au montage : le hook ne doit jamais "voir" le passage de undefined → uuid
  const [stableHookId] = useState<string | undefined>(() => threadId ?? undefined);

  // Body stable (référence unique) : le thread_id est lu via refs au moment de la requête
  const chatBody = useMemo(() => {
    const b: { thread_id?: string } = {};
    Object.defineProperty(b, "thread_id", {
      get: () => pendingThreadIdRef.current ?? threadIdRef.current ?? undefined,
      enumerable: true,
    });
    return b;
  }, []);

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
    id: stableHookId,
    api: CHAT_API,
    streamProtocol: "text",
    body: chatBody,
    headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : undefined,
    credentials: "include",
    onResponse: (res) => {
      const tid = res.headers.get("X-Thread-Id");
      console.log(FLOW, "stream response started", { status: res.status, xThreadId: tid });
    },
    onFinish: () => {
      console.log(FLOW, "stream finished");
      pendingThreadIdRef.current = null;
      setTimeout(() => mutate(THREADS_KEY), 1000);
    },
  });

  // Si l'utilisateur clique sur "Nouvelle conversation" (threadId passe d'un id à null), on vide l'affichage
  const prevThreadIdRef = useRef<string | null>(threadId);
  useEffect(() => {
    const prev = prevThreadIdRef.current;
    prevThreadIdRef.current = threadId;
    if (prev != null && threadId == null) {
      setMessages([]);
    }
  }, [threadId, setMessages]);

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
        if (cancelled) return;
        if (!data.messages?.length) return;
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

  useEffect(() => {
    if (showApproval) console.log(FLOW, "HITL: approval UI shown (Approuver / Rejeter)");
  }, [showApproval]);

  const handleApprove = useCallback(async () => {
    const tid = threadId ?? pendingThreadIdRef.current;
    if (!tid || !sessionToken) return;
    console.log(FLOW, "HITL: user clicked Approuver", { threadId: tid });
    try {
      const res = await fetch(`${BACKEND_URL}/api/chat/resume`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${sessionToken}`,
        },
        body: JSON.stringify({ thread_id: tid, action: "approve" }),
      });
      if (res.ok) {
        console.log(FLOW, "HITL: resume (approve) ok, reloading");
        reload();
      } else {
        console.warn(FLOW, "HITL: resume (approve) failed", res.status);
      }
    } catch (e) {
      console.warn(FLOW, "HITL: resume (approve) error", e);
    }
  }, [threadId, sessionToken, reload]);

  const handleReject = useCallback(async () => {
    const tid = threadId ?? pendingThreadIdRef.current;
    if (!tid || !sessionToken) return;
    console.log(FLOW, "HITL: user clicked Rejeter", { threadId: tid });
    try {
      const res = await fetch(`${BACKEND_URL}/api/chat/resume`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${sessionToken}`,
        },
        body: JSON.stringify({ thread_id: tid, action: "reject" }),
      });
      if (res.ok) {
        console.log(FLOW, "HITL: resume (reject) ok, reloading");
      } else {
        console.warn(FLOW, "HITL: resume (reject) failed", res.status);
      }
      reload();
    } catch (e) {
      console.warn(FLOW, "HITL: resume (reject) error", e);
      reload();
    }
  }, [threadId, sessionToken, reload]);

  const handleFormSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const userInput = input.trim();
    if (!userInput || !sessionToken) return;
    const effectiveThreadId = threadId ?? pendingThreadIdRef.current ?? "(new)";
    console.log(FLOW, "submit message", {
      threadId: effectiveThreadId,
      messagePreview: userInput.length > 80 ? userInput.slice(0, 80) + "…" : userInput,
    });
    if (!threadId) {
      const newId = uuidv4();
      pendingThreadIdRef.current = newId;
      window.history.replaceState(null, "", `/?threadId=${newId}`);
      onThreadCreated?.(newId);
      mutate(
        THREADS_KEY,
        (current: ThreadItem[] | undefined) => {
          const list = current ?? [];
          const optimistic: ThreadItem = {
            thread_id: newId,
            title: TEMP_TITLE,
            created_at: new Date().toISOString(),
          };
          return [optimistic, ...list];
        },
        { revalidate: false }
      );
    }
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
