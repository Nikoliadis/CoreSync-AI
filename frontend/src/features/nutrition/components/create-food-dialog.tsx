"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { type Food, nutritionApi, nutritionKeys } from "@/features/nutrition/api";
import {
  createFoodSchema,
  impliedCalories,
  type CreateFoodValues,
} from "@/features/nutrition/schemas";
import { ApiError } from "@/lib/api/client";

type Props = {
  /** Prefills the name from whatever they searched for and did not find. */
  initialName?: string;
  onCancel: () => void;
  onCreated: (food: Food) => void;
};

const EMPTY: CreateFoodValues = {
  name: "",
  caloriesPer100g: 0,
  proteinPer100g: 0,
  carbsPer100g: 0,
  fatPer100g: 0,
  alcoholPer100g: 0,
  isLiquid: false,
  servingLabel: "",
  servingGrams: undefined,
};

/**
 * A food of your own, private to you.
 *
 * This is the escape hatch for a catalogue that will never contain everything: rather
 * than abandoning the log, you add it once and it is in your recents from then on.
 */
export function CreateFoodDialog({ initialName, onCancel, onCreated }: Props) {
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const [showDrink, setShowDrink] = useState(false);

  const {
    control,
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<CreateFoodValues>({
    resolver: zodResolver(createFoodSchema),
    defaultValues: { ...EMPTY, name: initialName ?? "" },
  });

  // `useWatch` over named fields rather than a bare `watch()`: the latter returns a
  // fresh function every render, which opts this whole component out of the React
  // Compiler's memoization.
  const [protein, carbs, fat, alcohol, isLiquid] = useWatch({
    control,
    name: [
      "proteinPer100g",
      "carbsPer100g",
      "fatPer100g",
      "alcoholPer100g",
      "isLiquid",
    ],
  });

  const implied = Math.round(
    impliedCalories({
      proteinPer100g: Number(protein) || 0,
      carbsPer100g: Number(carbs) || 0,
      fatPer100g: Number(fat) || 0,
      alcoholPer100g: Number(alcohol) || 0,
    }),
  );

  const create = useMutation({
    mutationFn: (input: CreateFoodValues) =>
      nutritionApi.createFood({
        name: input.name,
        caloriesPer100g: input.caloriesPer100g,
        proteinPer100g: input.proteinPer100g,
        carbsPer100g: input.carbsPer100g,
        fatPer100g: input.fatPer100g,
        alcoholPer100g: input.alcoholPer100g,
        isLiquid: input.isLiquid,
        servings:
          input.servingLabel && input.servingGrams
            ? [{ label: input.servingLabel, grams: input.servingGrams }]
            : [],
      }),
    onSuccess: (food) => {
      void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
      toast.success(`${food.name} added`);
      onCreated(food);
    },
    onError: (error) => {
      // The server runs the same energy check and knows things the client cannot, so
      // its field messages win over the local ones.
      if (error instanceof ApiError) {
        const fieldErrors = error.fieldErrors;
        const keys = Object.keys(fieldErrors);
        if (keys.length > 0) {
          for (const key of keys) {
            if (key in EMPTY) {
              setError(key as keyof CreateFoodValues, { message: fieldErrors[key] });
            }
          }
          return;
        }
        setFormError(error.message);
        return;
      }
      setFormError("Couldn't reach the server. Check your connection and try again.");
    },
  });

  const onSubmit = handleSubmit((input) => {
    setFormError(null);
    return create.mutateAsync(input).catch(() => undefined);
  });

  const unit = isLiquid ? "100 ml" : "100 g";

  return (
    <Dialog open onOpenChange={(next) => !next && onCancel()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add your own food</DialogTitle>
        </DialogHeader>

        <form onSubmit={onSubmit} className="flex flex-col gap-3" noValidate>
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
            autoFocus
            error={errors.name?.message}
            {...register("name")}
          />

          <label className="flex items-center gap-2 text-caption text-text-secondary">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-border accent-accent"
              {...register("isLiquid")}
            />
            It&rsquo;s a drink, measured in millilitres
          </label>

          <p className="text-overline uppercase text-text-muted">Per {unit}</p>

          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Calories"
              inputMode="decimal"
              error={errors.caloriesPer100g?.message}
              // Macros alone imply the energy, so the hint is a live check rather than
              // a rule restated: it shows the number the label ought to say.
              hint={implied > 0 ? `Macros imply ~${implied} kcal` : undefined}
              {...register("caloriesPer100g", { valueAsNumber: true })}
            />
            <Input
              label="Protein (g)"
              inputMode="decimal"
              error={errors.proteinPer100g?.message}
              {...register("proteinPer100g", { valueAsNumber: true })}
            />
            <Input
              label="Carbs (g)"
              inputMode="decimal"
              error={errors.carbsPer100g?.message}
              {...register("carbsPer100g", { valueAsNumber: true })}
            />
            <Input
              label="Fat (g)"
              inputMode="decimal"
              error={errors.fatPer100g?.message}
              {...register("fatPer100g", { valueAsNumber: true })}
            />
          </div>

          {showDrink ? (
            <Input
              label="Alcohol (g)"
              inputMode="decimal"
              hint="Ethanol carries 7 kcal per gram."
              error={errors.alcoholPer100g?.message}
              {...register("alcoholPer100g", { valueAsNumber: true })}
            />
          ) : (
            <button
              type="button"
              onClick={() => setShowDrink(true)}
              className="self-start text-caption text-text-muted underline underline-offset-2 hover:text-text-secondary"
            >
              This one contains alcohol
            </button>
          )}

          <p className="text-overline uppercase text-text-muted">
            A serving <span className="normal-case text-text-muted">(optional)</span>
          </p>
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Called"
              placeholder="1 slice"
              error={errors.servingLabel?.message}
              {...register("servingLabel")}
            />
            <Input
              label={isLiquid ? "Millilitres" : "Grams"}
              inputMode="decimal"
              error={errors.servingGrams?.message}
              {...register("servingGrams", {
                setValueAs: (raw) => (raw === "" ? undefined : Number(raw)),
              })}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Saving…" : "Save food"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
