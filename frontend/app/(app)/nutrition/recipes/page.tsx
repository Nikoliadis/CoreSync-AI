"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChefHat, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  MEAL_LABELS,
  MEAL_ORDER,
  type MealType,
  type Recipe,
  nutritionApi,
  nutritionKeys,
} from "@/features/nutrition/api";
import { RecipeEditorDialog } from "@/features/nutrition/components/recipe-editor-dialog";
import { kcal, localToday, portion } from "@/features/nutrition/format";

export default function RecipesPage() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Recipe | null | "new">(null);
  const [logging, setLogging] = useState<Recipe | null>(null);

  const recipes = useQuery({
    queryKey: nutritionKeys.recipes(),
    queryFn: nutritionApi.recipes,
  });

  const remove = useMutation({
    mutationFn: nutritionApi.deleteRecipe,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
      toast.success("Recipe deleted", {
        description: "Meals you already logged from it are untouched.",
      });
    },
    onError: () => toast.error("Couldn't delete that recipe"),
  });

  const items = recipes.data ?? [];

  return (
    <>
      <TopBar
        title="Recipes"
        action={
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4" aria-hidden />
            New
          </Button>
        }
      />

      <PageShell className="max-w-3xl">
        {recipes.isLoading && (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </div>
        )}

        {recipes.isError && (
          <EmptyState
            icon={<ChefHat className="h-8 w-8" />}
            title="Couldn't load your recipes"
            action={<Button onClick={() => recipes.refetch()}>Try again</Button>}
          />
        )}

        {recipes.isSuccess && items.length === 0 && (
          <EmptyState
            icon={<ChefHat className="h-8 w-8" />}
            title="No recipes yet"
            description="Build a dish once, then log it in a single tap for as long as you keep making it."
            action={<Button onClick={() => setEditing("new")}>Create a recipe</Button>}
          />
        )}

        <ul className="flex flex-col gap-3">
          {items.map((recipe) => (
            <li key={recipe.id}>
              <Card>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-h3 text-text">{recipe.name}</p>
                    <p className="mt-0.5 text-caption text-text-muted">
                      <span className="tabular">{kcal(recipe.perServing.calories)}</span> kcal
                      per serving · makes{" "}
                      <span className="tabular">{portion(recipe.servingsCount)}</span> ·{" "}
                      <span className="tabular">{recipe.ingredients.length}</span>{" "}
                      {recipe.ingredients.length === 1 ? "ingredient" : "ingredients"}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center">
                    <button
                      type="button"
                      onClick={() => setEditing(recipe)}
                      className="flex h-11 w-11 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-well hover:text-text"
                      aria-label={`Edit ${recipe.name}`}
                    >
                      <Pencil className="h-4 w-4" aria-hidden />
                    </button>
                    <button
                      type="button"
                      onClick={() => remove.mutate(recipe.id)}
                      className="flex h-11 w-11 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-well hover:text-critical"
                      aria-label={`Delete ${recipe.name}`}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </button>
                  </div>
                </div>

                {recipe.hasMissingIngredients && (
                  /* Said out loud rather than hidden: the totals under-report while this
                     is true, and a wrong calorie count that looks fine is the worst of
                     both. */
                  <p className="mt-2 flex items-center gap-1.5 text-caption text-warning">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    An ingredient is missing, so these totals are too low.
                  </p>
                )}

                {recipe.ingredients.length > 0 && (
                  <>
                    <p className="mt-3 truncate text-caption text-text-secondary">
                      {recipe.ingredients.map((i) => i.foodName).join(", ")}
                    </p>
                    <div className="mt-3">
                      <Button size="sm" variant="ghost" onClick={() => setLogging(recipe)}>
                        Log a serving
                      </Button>
                    </div>
                  </>
                )}
              </Card>
            </li>
          ))}
        </ul>
      </PageShell>

      {editing !== null && (
        <RecipeEditorDialog
          recipe={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}

      {logging && <LogRecipeDialog recipe={logging} onClose={() => setLogging(null)} />}
    </>
  );
}

function LogRecipeDialog({ recipe, onClose }: { recipe: Recipe; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [servings, setServings] = useState("1");
  const [meal, setMeal] = useState<MealType>("dinner");

  const amount = Number(servings) || 0;
  const preview = Math.round(Number(recipe.perServing.calories) * amount);

  const log = useMutation({
    mutationFn: () =>
      nutritionApi.logRecipe(recipe.id, {
        mealType: meal,
        servings: amount,
        localDate: localToday(),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
      toast.success(`${recipe.name} logged`);
      onClose();
    },
    onError: () => toast.error("Couldn't log that"),
  });

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{recipe.name}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <Input
            label="Servings"
            autoFocus
            inputMode="decimal"
            value={servings}
            onChange={(event) => setServings(event.target.value)}
          />

          <fieldset className="flex flex-col gap-1">
            <legend className="text-caption text-text-muted">Meal</legend>
            <div className="flex flex-wrap gap-1.5">
              {MEAL_ORDER.map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={meal === option}
                  onClick={() => setMeal(option)}
                  className={
                    meal === option
                      ? "rounded-full border border-accent bg-accent/10 px-3 py-1.5 text-caption text-text"
                      : "rounded-full border border-border px-3 py-1.5 text-caption text-text-secondary transition-colors hover:bg-surface-well"
                  }
                >
                  {MEAL_LABELS[option]}
                </button>
              ))}
            </div>
          </fieldset>

          <p className="text-body text-text-secondary">
            <span className="tabular text-h2 text-text">{preview}</span> kcal
          </p>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => log.mutate()} disabled={amount <= 0 || log.isPending}>
            {log.isPending ? "Adding…" : "Add to diary"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
