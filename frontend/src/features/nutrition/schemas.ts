import { z } from "zod";

/**
 * Mirrors the backend's constraints so the user gets an answer before a round trip.
 * The server remains the authority — this is a courtesy, never the enforcement.
 */

// Atwater factors. Ethanol is here because it is 7 kcal/g and is none of the three
// macros: without it, every spirit looks like a typo.
export const KCAL_PER_G = { protein: 4, carbs: 4, fat: 9, alcohol: 7 } as const;

/** The absolute floor and the proportional band, both matching the CHECK constraint. */
const ENERGY_TOLERANCE_KCAL = 50;
const ENERGY_TOLERANCE_SHARE = 0.25;

const amount = (max: number, label: string) =>
  z
    .number({ invalid_type_error: `Enter a number for ${label}.` })
    .min(0, `${label} can't be negative.`)
    .max(max, `${max} is the most we'll accept for ${label}.`);

export const impliedCalories = (values: {
  proteinPer100g: number;
  carbsPer100g: number;
  fatPer100g: number;
  alcoholPer100g: number;
}): number =>
  values.proteinPer100g * KCAL_PER_G.protein +
  values.carbsPer100g * KCAL_PER_G.carbs +
  values.fatPer100g * KCAL_PER_G.fat +
  values.alcoholPer100g * KCAL_PER_G.alcohol;

export const createFoodSchema = z
  .object({
    name: z.string().trim().min(1, "Give it a name.").max(200, "That's longer than 200 characters."),
    caloriesPer100g: amount(1000, "calories"),
    proteinPer100g: amount(100, "protein"),
    carbsPer100g: amount(100, "carbs"),
    fatPer100g: amount(100, "fat"),
    alcoholPer100g: amount(100, "alcohol"),
    isLiquid: z.boolean(),
    servingLabel: z.string().trim().max(80, "That's longer than 80 characters.").optional(),
    servingGrams: z.number().min(0).max(10_000).optional(),
  })
  .superRefine((values, ctx) => {
    // The same reconciliation the database enforces, run early so the message can say
    // what the number should have been rather than surfacing as a rejected save. A
    // misplaced decimal point is the failure that matters: telling someone they ate 40
    // kcal when they ate 400 is worse than refusing the row.
    const implied = impliedCalories(values);
    const tolerance = Math.max(
      ENERGY_TOLERANCE_KCAL,
      values.caloriesPer100g * ENERGY_TOLERANCE_SHARE,
    );
    if (values.caloriesPer100g > 0 && Math.abs(values.caloriesPer100g - implied) > tolerance) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["caloriesPer100g"],
        message: `Those macros work out to about ${Math.round(implied)} kcal. Check the label.`,
      });
    }

    // A serving is a label and a weight together; half of one is not usable.
    if (values.servingLabel && !values.servingGrams) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["servingGrams"],
        message: "How much does one weigh?",
      });
    }
    if (values.servingGrams && !values.servingLabel) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["servingLabel"],
        message: "What should we call it?",
      });
    }
  });

export type CreateFoodValues = z.infer<typeof createFoodSchema>;
