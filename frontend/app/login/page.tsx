"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSignUp, setIsSignUp] = useState(false);

  const supabase = createClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (isSignUp) {
        const { error: signUpError } = await supabase.auth.signUp({ email, password });
        if (signUpError) throw signUpError;
        setError(null);
        setPassword("");
        // Optional: show "Check your email" message
      } else {
        const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
        if (signInError) throw signInError;
        window.location.href = "/";
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Une erreur est survenue.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 p-4">
      <Card className="w-full max-w-md border-zinc-700 bg-zinc-900">
        <CardHeader>
          <CardTitle className="text-center text-xl text-zinc-100">
            Volteyr
          </CardTitle>
          <p className="text-center text-sm text-zinc-400">
            {isSignUp ? "Créer un compte" : "Connexion"}
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="mb-1 block text-sm text-zinc-400">
                Email
              </label>
              <Input
                id="email"
                type="email"
                placeholder="vous@exemple.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
                className="border-zinc-600 bg-zinc-800"
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1 block text-sm text-zinc-400">
                Mot de passe
              </label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete={isSignUp ? "new-password" : "current-password"}
                className="border-zinc-600 bg-zinc-800"
              />
            </div>
            {error && (
              <p className="text-sm text-red-400">{error}</p>
            )}
            <Button
              type="submit"
              className="w-full"
              variant="secondary"
              disabled={loading}
            >
              {loading ? "Chargement…" : isSignUp ? "S&apos;inscrire" : "Se connecter"}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-zinc-500">
            {isSignUp ? (
              <>
                Déjà un compte ?{" "}
                <button
                  type="button"
                  onClick={() => setIsSignUp(false)}
                  className="text-zinc-300 underline hover:text-white"
                >
                  Se connecter
                </button>
              </>
            ) : (
              <>
                Pas de compte ?{" "}
                <button
                  type="button"
                  onClick={() => setIsSignUp(true)}
                  className="text-zinc-300 underline hover:text-white"
                >
                  S&apos;inscrire
                </button>
              </>
            )}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
