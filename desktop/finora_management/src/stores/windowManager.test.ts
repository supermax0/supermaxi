import { useWindowManager } from "./windowManager";

const wm = () => useWindowManager.getState();

describe("window manager", () => {
  beforeEach(() => wm().reset());

  it("opens one window at a time and records the window that left", () => {
    wm().open("orders");
    expect(wm()).toMatchObject({ active: "orders", previous: null });
    wm().open("products");
    expect(wm()).toMatchObject({ active: "products", previous: "orders" });
  });

  it("toggle on the active window closes it back to its button", () => {
    wm().toggle("purchases");
    wm().toggle("purchases");
    expect(wm()).toMatchObject({ active: null, previous: "purchases" });
  });

  it("re-opening the active window is a no-op (no extra animation)", () => {
    wm().open("orders");
    const revision = wm().revision;
    wm().open("orders");
    expect(wm().revision).toBe(revision);
  });

  it("rapid switching always settles on the last requested window", () => {
    const sequence = [
      "orders",
      "products",
      "purchases",
      "orders",
      "products",
      "purchases",
      "orders",
    ] as const;
    for (const id of sequence) wm().open(id);
    expect(wm().active).toBe("orders");
    expect(wm().previous).toBe("purchases");
    expect(wm().revision).toBe(sequence.length);
  });

  it("minimize marks the window on its button until it is opened again", () => {
    wm().open("products");
    wm().minimize();
    expect(wm().active).toBeNull();
    expect(wm().minimized.has("products")).toBe(true);
    wm().open("products");
    expect(wm().minimized.has("products")).toBe(false);
  });

  it("close and minimize without an active window change nothing", () => {
    wm().close();
    wm().minimize();
    expect(wm().revision).toBe(0);
  });

  it("expanded mode toggles independently of the active window", () => {
    wm().toggleExpanded();
    wm().open("orders");
    expect(wm().expanded).toBe(true);
  });
});
