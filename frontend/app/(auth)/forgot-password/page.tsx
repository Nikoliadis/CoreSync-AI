"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Mail } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { authApi } from "@/features/auth/api";
import { forgotPasswordSchema, type ForgotPasswordValues } from "@/features/auth/schemas";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);

  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<ForgotPasswordValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    // Deliberately ignores the outcome. The endpoint answers identically for a
    // known and an unknown address, and surfacing an error here would rebuild
    // the account-enumeration oracle the backend is careful to avoid (docs/11).
    try {
      await authApi.requestPasswordReset(values.email);
    } catch {
      // Same path either way.
    }
    setSent(true);
  });

  if (sent) {
    return (
      <Card padding="lg">
        <h1 className="text-h2 text-text">Check your email</h1>
        <p className="mt-2 text-body text-text-secondary">
          If an account exists for <span className="text-text">{getValues("email")}</span>, a reset
          link is on its way. It expires in 30 minutes.
        </p>
        <Button variant="secondary" block className="mt-6" asChild>
          <Link href="/login">Back to login</Link>
        </Button>
      </Card>
    );
  }

  return (
    <div>
      <h1 className="text-h1 text-text">Reset your password</h1>
      <p className="mt-1 text-body text-text-secondary">
        We&apos;ll email you a link to set a new one.
      </p>

      <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-4" noValidate>
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          autoFocus
          leadingIcon={<Mail className="h-4 w-4" />}
          error={errors.email?.message}
          {...register("email")}
        />

        <Button type="submit" size="lg" block loading={isSubmitting}>
          Send reset link
        </Button>
      </form>

      <p className="mt-6 text-center text-body text-text-secondary">
        Remembered it?{" "}
        <Link href="/login" className="text-accent-text underline underline-offset-2">
          Log in
        </Link>
      </p>
    </div>
  );
}
