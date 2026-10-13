import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";
import { installFakeEventSource } from "./fakeEventSource";

// Every test starts with a fresh controllable EventSource registry.
beforeEach(() => {
  installFakeEventSource();
});
