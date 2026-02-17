"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ApprovalRequestProps {
  onApprove: () => void;
  onReject: () => void;
  loading?: boolean;
}

/**
 * Affiche les boutons Approuver / Rejeter lorsque l’agent est en pause (HITL, ex. envoi d’email).
 * En Phase 5 on l’affiche après chaque réponse ; plus tard on pourra ne l’afficher que lorsque
 * le stream contient un part "data-hitl-pause" ou un header X-Volteyr-Action: approve_email.
 */
export function ApprovalRequest({
  onApprove,
  onReject,
  loading = false,
}: ApprovalRequestProps) {
  return (
    <div className="border-t border-zinc-800 bg-zinc-900/70 px-4 py-3">
      <div className="mx-auto flex max-w-3xl items-center justify-between gap-4">
        <span className="text-sm text-zinc-400">
          Action en attente de validation (ex. envoi d’email)
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onReject}
            disabled={loading}
            className="border-zinc-600 text-zinc-300 hover:bg-zinc-800"
          >
            Rejeter
          </Button>
          <Button
            size="sm"
            onClick={onApprove}
            disabled={loading}
            variant="secondary"
          >
            Approuver
          </Button>
        </div>
      </div>
    </div>
  );
}
