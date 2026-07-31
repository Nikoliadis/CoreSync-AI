import { z } from "zod";

/**
 * Mirrors the backend's constraints so the user gets an answer before a round
 * trip. The server remains the authority — this is a courtesy, never the
 * enforcement (docs/07 §5).
 */

// 10 characters matches `RegisterRequest.password` on the backend. Length beats
// composition rules: a passphrase is both stronger and easier to remember than
// `P@ssw0rd!` (docs/06).
const password = z
  .string()
  .min(10, "Use at least 10 characters — a short phrase works well.")
  .max(128, "That's longer than 128 characters.");

export const loginSchema = z.object({
  email: z.string().min(1, "Enter your email.").email("That doesn't look like an email address."),
  password: z.string().min(1, "Enter your password."),
});

export const registerSchema = z.object({
  displayName: z
    .string()
    .min(1, "What should we call you?")
    .max(80, "That's longer than 80 characters."),
  email: z.string().min(1, "Enter your email.").email("That doesn't look like an email address."),
  password,
  acceptedTerms: z.literal(true, {
    errorMap: () => ({ message: "You'll need to accept the terms to continue." }),
  }),
});

export const forgotPasswordSchema = z.object({
  email: z.string().min(1, "Enter your email.").email("That doesn't look like an email address."),
});

export const resetPasswordSchema = z
  .object({
    password,
    confirmPassword: z.string(),
  })
  .refine((values) => values.password === values.confirmPassword, {
    message: "Those don't match.",
    path: ["confirmPassword"],
  });

export type LoginValues = z.infer<typeof loginSchema>;
export type RegisterValues = z.infer<typeof registerSchema>;
export type ForgotPasswordValues = z.infer<typeof forgotPasswordSchema>;
export type ResetPasswordValues = z.infer<typeof resetPasswordSchema>;
