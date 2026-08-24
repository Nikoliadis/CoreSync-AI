"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
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
import { type Food, type Recipe, nutritionApi, nutritionKeys } from "@/features/nutrition/api";
import { IngredientPicker } from "@/features/nutrition/components/ingredient-picker";
import { portion } from "@/features/nutrition/format";
import { ApiError } from "@/lib/api/client";

type DraftIngredient = {
  /** Local only — the server mints the real ids when the recipe is saved. */
  key: string;
  foodId: string;
  foodName: string;
  grams: string;
};

/**
 * Create or edit a recipe.
 *
 * The whole ingredient list is sent on save rather than a diff. Editing a recipe is a
 * session of several changes — add two, remove one, adjust a weight — and reconciling
 * that client-side would put the hardest part in the least reliable place.
 */
export function RecipeEditorDialog({
  recipe,
  onClose,
}: {
  recipe: Recipe | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(recipe?.name ?? "");
  const [servings, setServings] = useState(recipe?.servingsCount ?? "1");
  const [picking, setPicking] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [ingredients, setIngredients] = useState<DraftIngredient[]>(
    () =>
      recipe?.ingredients.map((i) => ({
        key: i.id,
        foodId: i.foodId,
        foodName: i.foodName,
        grams: portion(i.grams),
      })) ?? [],
  );

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: name.trim(),
        servingsCount: Number(servings) || 0,
        ingredients: ingredients.map((i) => ({
          foodId: i.foodId,
          grams: Number(i.grams) || 0,
        })),
      };
      return recipe
        ? nutritionApi.updateRecipe(recipe.id, payload)
        : nutritionApi.createRecipe(payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
      toast.success(recipe ? "Recipe saved" : "Recipe created");
      onClose();
    },
    onError: (error) => {
      setFormError(
        error instanceof ApiError
          ? error.message
          : "Couldn't reach the server. Check your connection and try again.",
      );
    },
  });

  const addIngredient = (food: Food) => {
    setIngredients((current) => [
      ...current,
      {
        key: `${food.id}-${current.length}`,
        foodId: food.id,
        foodName: food.name,
        // A default that is almost always wrong but never blocks: 100 g is the unit the
        // macros are quoted in, so the number on screen matches the label they are reading.
        grams: "100",
      },
    ]);
    setPicking(false);
  };

  if (picking) {
    return <IngredientPicker onPick={addIngredient} onCancel={() => setPicking(false)} />;
  }

  const servingCount = Number(servings) || 0;
  const canSave = name.trim().length > 0 && servingCount > 0 && !save.isPending;

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{recipe ? "Edit recipe" : "New recipe"}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
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
            value={name}
            onChange={(event) => setName(event.target.value)}
          />

          <Input
            label="Servings it makes"
            inputMode="decimal"
            value={servings}
            onChange={(event) => setServings(event.target.value)}
            hint="Used to work out the per-serving macros."
          />

          <div className="flex items-center justify-between gap-3">
            <p className="text-overline uppercase text-text-muted">Ingredients</p>
            <Button size="sm" variant="ghost" onClick={() => setPicking(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              Add
            </Button>
          </div>

          {ingredients.length === 0 ? (
            <p className="text-caption text-text-muted">
              No ingredients yet. You can save it now and fill them in later.
            </p>
          ) : (
            <ul className="flex max-h-[35vh] flex-col overflow-y-auto">
              {ingredients.map((ingredient, index) => (
                <li
                  key={ingredient.key}
                  className="flex items-center gap-2 border-t border-border py-2 first:border-t-0"
                >
                  <span className="min-w-0 flex-1 truncate text-body text-text">
                    {ingredient.foodName}
                  </span>
                  <Input
                    inputMode="decimal"
                    value={ingredient.grams}
                    aria-label={`Grams of ${ingredient.foodName}`}
                    className="w-24"
                    onChange={(event) =>
                      setIngredients((current) =>
                        current.map((item, i) =>
                          i === index ? { ...item, grams: event.target.value } : item,
                        ),
                      )
                    }
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setIngredients((current) => current.filter((_, i) => i !== index))
                    }
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-well hover:text-critical"
                    aria-label={`Remove ${ingredient.foodName}`}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={!canSave}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
