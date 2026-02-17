import { Suspense } from "react";
import { ChatLayout } from "@/components/chat/ChatLayout";

export default function HomePage() {
  return (
    <Suspense fallback={<div className="flex h-screen items-center justify-center bg-zinc-950 text-zinc-500">Chargement…</div>}>
      <ChatLayout />
    </Suspense>
  );
}
