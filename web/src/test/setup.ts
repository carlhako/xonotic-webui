import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";
import { installFakeEventSource } from "./fakeEventSource";

// Every test starts with a fresh controllable EventSource registry.
beforeEach(() => {
  installFakeEventSource();
});

// jsdom has no modal dialog: give <dialog> the open/close behaviour the app relies on.
if (typeof HTMLDialogElement !== "undefined") {
  const proto = HTMLDialogElement.prototype as HTMLDialogElement & {
    showModal?: () => void;
  };
  proto.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
    // the dialog focusing steps: the first focusable control inside gets focus
    this.querySelector<HTMLElement>("button, [href], input, select, textarea")?.focus();
  };
  proto.close = function close(this: HTMLDialogElement) {
    if (!this.hasAttribute("open")) return;
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
}
