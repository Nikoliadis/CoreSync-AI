"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardList, Plus, Trash2 } from "lucide-react";
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
import { groupByFolder, routineKeys, routinesApi } from "@/features/workouts/routines-api";

export default function RoutinesPage() {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [folder, setFolder] = useState("");

  const routines = useQuery({ queryKey: routineKeys.list(), queryFn: routinesApi.list });
  const templates = useQuery({
    queryKey: routineKeys.templates(),
    queryFn: routinesApi.templates,
    // Curated reference data — refetching it on every visit is wasted bandwidth.
    staleTime: 10 * 60_000,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: routineKeys.all });
  };

  const create = useMutation({
    mutationFn: () =>
      routinesApi.create({ name: name.trim(), folder: folder.trim() || null }),
    onSuccess: () => {
      invalidate();
      setCreating(false);
      setName("");
      setFolder("");
      toast.success("Routine created");
    },
    onError: () => toast.error("Couldn't create that routine"),
  });

  const adopt = useMutation({
    mutationFn: routinesApi.adopt,
    onSuccess: () => {
      invalidate();
      toast.success("Added to your routines", {
        description: "It's a copy — editing it won't change the template.",
      });
    },
    onError: () => toast.error("Couldn't add that template"),
  });

  const remove = useMutation({
    mutationFn: routinesApi.remove,
    onSuccess: () => {
      invalidate();
      toast.success("Routine deleted");
    },
    onError: () => toast.error("Couldn't delete that routine"),
  });

  const grouped = groupByFolder(routines.data ?? []);

  return (
    <>
      <TopBar
        title="Routines"
        action={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            New
          </Button>
        }
      />

      <PageShell className="max-w-4xl">
        {routines.isLoading && (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        )}

        {routines.isError && (
          <EmptyState
            icon={<ClipboardList className="h-8 w-8" />}
            title="Couldn't load your routines"
            action={<Button onClick={() => routines.refetch()}>Try again</Button>}
          />
        )}

        {routines.isSuccess && grouped.length === 0 && (
          <EmptyState
            icon={<ClipboardList className="h-8 w-8" />}
            title="No routines yet"
            description="Build one from scratch, or start from a template below."
            action={<Button onClick={() => setCreating(true)}>Create a routine</Button>}
          />
        )}

        {grouped.map(([folderName, items]) => (
          <section key={folderName || "unfiled"} className="mb-6">
            <h2 className="mb-2 text-overline uppercase text-text-muted">
              {folderName || "Unfiled"}
            </h2>
            <ul className="flex flex-col gap-2">
              {items.map((routine) => (
                <li key={routine.id}>
                  <Card className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-h3 text-text">{routine.name}</p>
                      <p className="mt-0.5 text-caption text-text-muted">
                        <span className="tabular">{routine.exercises.length}</span>{" "}
                        {routine.exercises.length === 1 ? "exercise" : "exercises"}
                        {routine.lastPerformedAt
                          ? ` · last done ${routine.lastPerformedAt.slice(0, 10)}`
                          : " · never performed"}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => remove.mutate(routine.id)}
                      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-well hover:text-critical"
                      aria-label={`Delete ${routine.name}`}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </button>
                  </Card>
                </li>
              ))}
            </ul>
          </section>
        ))}

        {/* --- templates --------------------------------------------------- */}
        {templates.data && templates.data.length > 0 && (
          <section>
            <h2 className="mb-2 text-overline uppercase text-text-muted">Starter templates</h2>
            <ul className="grid gap-2 sm:grid-cols-2">
              {templates.data.map((template) => (
                <li key={template.id}>
                  <Card className="flex h-full items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-body text-text">{template.name}</p>
                      <p className="text-caption text-text-muted">
                        <span className="tabular">{template.exercises.length}</span> exercises
                      </p>
                    </div>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => adopt.mutate(template.id)}
                      loading={adopt.isPending && adopt.variables === template.id}
                    >
                      Use
                    </Button>
                  </Card>
                </li>
              ))}
            </ul>
          </section>
        )}
      </PageShell>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent variant="sheet">
          <DialogHeader>
            <DialogTitle>New routine</DialogTitle>
          </DialogHeader>

          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim()) create.mutate();
            }}
            className="flex flex-col gap-4"
          >
            <Input
              label="Name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Push day"
              maxLength={120}
              autoFocus
              required
            />
            <Input
              label="Folder"
              hint="Optional — groups routines in the list."
              value={folder}
              onChange={(event) => setFolder(event.target.value)}
              placeholder="PPL"
              maxLength={80}
            />

            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={create.isPending} disabled={!name.trim()}>
                Create
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
