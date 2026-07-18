import "@testing-library/jest-dom/vitest";

if (HTMLElement.prototype.scrollTo === undefined) {
  HTMLElement.prototype.scrollTo = vi.fn();
}

Object.defineProperty(window, "matchMedia", {
  configurable: true,
  writable: true,
  value: vi.fn().mockImplementation(() => ({
    matches: false,
    media: "",
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});
