"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Eye, EyeOff, Lock, Mail } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { useAuthActions } from "@/features/auth/hooks";
import { loginSchema, type LoginValues } from "@/features/auth/schemas";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SocialSignIn } from "@/features/auth/components/social-sign-in";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuthActions();
  const [showPassword, setShowPassword] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login(values);
      router.replace("/dashboard");
    } catch (error) {
      if (error instanceof ApiError) {
        // Field-level messages where the API gave them; otherwise one message
        // above the form. Never "Error 401" — say what to do next (docs/09 §10).
        const fieldErrors = error.fieldErrors;
        const keys = Object.keys(fieldErrors);
        if (keys.length > 0) {
          for (const key of keys) {
            if (key === "email" || key === "password") {
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
      <h1 className="text-h1 text-text">Welcome back</h1>
      <p className="mt-1 text-body text-text-secondary">Pick up where you left off.</p>

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
          label="Email"
          type="email"
          autoComplete="email"
          autoFocus
          leadingIcon={<Mail className="h-4 w-4" />}
          error={errors.email?.message}
          {...register("email")}
        />

        <Input
          label="Password"
          type={showPassword ? "text" : "password"}
          autoComplete="current-password"
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

        <div className="flex justify-end">
          <Link href="/forgot-password" className="text-caption text-accent-text hover:underline">
            Forgot password?
          </Link>
        </div>

        <Button type="submit" size="lg" block loading={isSubmitting}>
          Log in
        </Button>
      </form>

      <div className="mt-4">
        <SocialSignIn onSuccess={() => router.replace("/dashboard")} />
      </div>

      <p className="mt-6 text-center text-body text-text-secondary">
        New here?{" "}
        <Link href="/register" className="text-accent-text underline underline-offset-2">
          Create an account
        </Link>
      </p>
    </div>
  );
}
