import { AnimatePresence, motion } from "framer-motion";
import { Check, Loader2, X } from "lucide-react";
import { ToolActivity } from "@/lib/protocol";
import { cn } from "@/lib/utils";

/** Floating telemetry chip showing what tool Elara is running. */
export function ToolBadge({ tool }: { tool: ToolActivity | null }) {
  return (
    <div className="pointer-events-none absolute left-1/2 top-4 z-30 -translate-x-1/2">
      <AnimatePresence>
        {tool && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            role="status"
            className={cn(
              "telemetry flex items-center gap-2.5 rounded-full border border-border bg-popover/90 px-4 py-2 text-foreground/90 shadow-lg backdrop-blur",
              tool.status === "error" && "border-destructive/50"
            )}
          >
            {tool.status === "start" && (
              <Loader2 className="size-3.5 animate-spin text-elara-glow" />
            )}
            {tool.status === "done" && (
              <Check className="size-3.5 text-success" />
            )}
            {tool.status === "error" && (
              <X className="size-3.5 text-destructive" />
            )}
            {tool.name}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
