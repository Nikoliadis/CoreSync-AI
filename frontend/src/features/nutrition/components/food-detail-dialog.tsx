"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Send, Star } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { nutritionApi, nutritionKeys } from "@/features/nutrition/api";
import { kcal, portion } from "@/features/nutrition/format";

const TIER_LABEL: Record<number, string> = {
  1: "Verified — checked by hand",
  2: "Reviewed — checked by a moderator",
  3: "Community data — not verified",
  4: "Your own food",
};

export function FoodDetailDialog({
  foodId,
  isFavourite,
  onClose,
}: {
  foodId: string;
  isFavourite?: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: nutritionKeys.food(foodId),
    queryFn: () => nutritionApi.food(foodId),
  });

  const favourite = useMutation({
    mutationFn: (next: boolean) =>
      next ? nutritionApi.addFavourite(foodId) : nutritionApi.removeFavourite(foodId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
    },
    onError: () => toast.error("Couldn't update that"),
  });

  const submit = useMutation({
    mutationFn: () => nutritionApi.submitFood(foodId),
    onSuccess: () =>
      toast.success("Sent for review", {
        description: "A moderator will check the numbers before it goes public.",
      }),
    onError: () => toast.error("Couldn't send that"),
  });

  const food = detail.data?.food;
  const nutrients = detail.data?.nutrients ?? [];
  const unit = food?.isLiquid ? "100 ml" : "100 g";

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{food?.name ?? "Food"}</DialogTitle>
        </DialogHeader>

        {detail.isLoading && (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        )}

        {food && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              {food.isVerified && (
                <BadgeCheck className="h-4 w-4 shrink-0 text-accent" aria-hidden />
              )}
              <span className="text-caption text-text-muted">
                {TIER_LABEL[food.trustTier] ?? "Unknown provenance"}
              </span>
            </div>

            <div>
              <p className="text-overline uppercase text-text-muted">Per {unit}</p>
              <dl className="mt-2 flex flex-col">
                <Row label="Calories" value={`${kcal(food.caloriesPer100g)} kcal`} />
                <Row label="Protein" value={`${portion(food.proteinPer100g)} g`} />
                <Row label="Carbs" value={`${portion(food.carbsPer100g)} g`} />
                <Row label="Fat" value={`${portion(food.fatPer100g)} g`} />
                {Number(food.alcoholPer100g) > 0 && (
                  <Row label="Alcohol" value={`${portion(food.alcoholPer100g)} g`} />
                )}
              </dl>
            </div>

            {nutrients.length > 0 ? (
              <div>
                <p className="text-overline uppercase text-text-muted">
                  Also measured
                </p>
                <dl className="mt-2 flex max-h-56 flex-col overflow-y-auto">
                  {nutrients.map((nutrient) => (
                    <Row
                      key={nutrient.code}
                      label={nutrient.name}
                      value={`${portion(nutrient.amountPer100g)} ${nutrient.unit}`}
                    />
                  ))}
                </dl>
              </div>
            ) : (
              /* Absent is not zero. Saying "no data" is honest; showing 0 mg of sodium
                 for a food nobody measured would be a fabrication. */
              <p className="text-caption text-text-muted">
                No further nutrients recorded for this food.
              </p>
            )}

            {food.servings.length > 0 && (
              <div>
                <p className="text-overline uppercase text-text-muted">Servings</p>
                <dl className="mt-2 flex flex-col">
                  {food.servings.map((serving) => (
                    <Row
                      key={serving.id}
                      label={serving.label}
                      value={`${portion(serving.grams)} ${food.isLiquid ? "ml" : "g"}`}
                    />
                  ))}
                </dl>
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="ghost"
                disabled={favourite.isPending}
                onClick={() => favourite.mutate(!isFavourite)}
              >
                <Star
                  className={
                    isFavourite ? "h-4 w-4 fill-accent text-accent" : "h-4 w-4"
                  }
                  aria-hidden
                />
                {isFavourite ? "Starred" : "Star"}
              </Button>

              {food.isCustom && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={submit.isPending || submit.isSuccess}
                  onClick={() => submit.mutate()}
                >
                  <Send className="h-4 w-4" aria-hidden />
                  {submit.isSuccess ? "Sent for review" : "Offer to everyone"}
                </Button>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-border py-1.5 first:border-t-0">
      <dt className="text-caption text-text-secondary">{label}</dt>
      <dd className="tabular text-caption text-text">{value}</dd>
    </div>
  );
}
