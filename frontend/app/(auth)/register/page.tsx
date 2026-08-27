"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Eye, EyeOff, Lock, Mail, User } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { useAuthActions } from "@/features/auth/hooks";
import { registerSchema, type RegisterValues } from "@/features/auth/schemas";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SocialSignIn } from "@/features/auth/components/social-sign-in";

export default function RegisterPage() {
  const router = useRouter();
  const { register: signUp } = useAuthActions();
  const [showPassword, setShowPassword] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { displayName: "", email: "", password: "", acceptedTerms: false as true },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await signUp({
        displayName: values.displayName,
        email: values.email,
        password: values.password,
        acceptedTerms: values.acceptedTerms,
        // Sent from the browser so streaks, calendars and quota resets land on
        // the user's day rather than UTC's (docs/03).
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      });
      router.replace("/dashboard");
    } catch (error) {
      if (error instanceof ApiError) {
        const fieldErrors = error.fieldErrors;
        const keys = Object.keys(fieldErrors);
        if (keys.length > 0) {
          for (const key of keys) {
            if (key === "email" || key === "password" || key === "displayName") {
              setError(key, { message: fieldErrors[key] });
            }
          }
        } else {
          setFormError(error.message);
        }
      } else {
        setFormError("Couldn't reach the server. Check your connection and try again.");
      }
    }
  });

  return (
    <div>
      <h1 className="text-h1 text-text">Create your account</h1>
      <p className="mt-1 text-body text-text-secondary">Takes about a minute.</p>

      <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-4" noValidate>
        {formError && (
          <div
            role="alert"
            className="rounded-md border border-critical/40 bg-critical/10 p-3 text-caption text-critical"
          >
            {formError}
          </div>
        )}

        <Input
          label="Name"
          autoComplete="name"
          autoFocus
          leadingIcon={<User className="h-4 w-4" />}
          error={errors.displayName?.message}
          {...register("displayName")}
        />

        <Input
          label="Email"
          type="email"
          autoComplete="email"
          leadingIcon={<Mail className="h-4 w-4" />}
          error={errors.email?.message}
          {...register("email")}
        />

        <Input
          label="Password"
          type={showPassword ? "text" : "password"}
          autoComplete="new-password"
          hint="At least 10 characters. A short phrase is stronger than a clever word."
          leadingIcon={<Lock className="h-4 w-4" />}
          error={errors.password?.message}
          trailingSlot={
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="flex h-9 w-9 items-center justify-center rounded-sm text-text-muted hover:text-text"
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          }
          {...register("password")}
        />

        <div className="flex flex-col gap-1.5">
          <label className="flex items-start gap-2.5 text-caption text-text-secondary">
            {/* Never pre-ticked: consent is captured explicitly, and the backend
                rejects the request if this is false (docs/11). */}
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 rounded-sm accent-[var(--color-accent)]"
              {...register("acceptedTerms")}
            />
            <span>
              {/* Linked, and opening in a new tab so reading it does not discard a
                  half-filled form. Asking somebody to accept a document they cannot
                  open is not consent. */}
              I accept the terms of service and{" "}
              <Link
                href="/privacy"
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent-text underline underline-offset-4"
              >
                privacy policy
              </Link>
              .
            </span>
          </label>
          {errors.acceptedTerms && (
            <p role="alert" className="text-caption text-critical">
              {errors.acceptedTerms.message}
            </p>
          )}
        </div>

        <Button type="submit" size="lg" block loading={isSubmitting}>
          Create account
        </Button>
      </form>

      <div className="mt-4">
        {/* Same component on both pages: with a social provider there is no separate
            "register" — the first successful sign-in creates the account. */}
        <SocialSignIn onSuccess={() => router.replace("/dashboard")} />
      </div>

      <p className="mt-6 text-center text-body text-text-secondary">
        Already have an account?{" "}
        <Link href="/login" className="text-accent-text underline underline-offset-2">
          Log in
        </Link>
      </p>
    </div>
  );
}
