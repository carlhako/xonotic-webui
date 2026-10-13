import type { ApplyClass } from "../api/client";

/** What an operator is told after a save, per apply class. `running` is whether the
 *  server was running when the change was saved. */
export function applyMessage(apply: ApplyClass, running: boolean): string {
  if (!running && apply !== "now") return "Saved; applies when the server starts";
  switch (apply) {
    case "now":
      return running ? "Applied" : "Saved; applies when the server starts";
    case "next_map":
      return "Applies at the next map";
    case "next_start":
      return "Applies when the server restarts";
    case "may_need_restart":
      return "May need a map change or restart";
  }
}
