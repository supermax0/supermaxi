import { createTypingFeedback } from "./typingFeedback";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});
function fixture(type = "text") {
  const field = document.createElement("input");
  field.type = type;
  document.body.append(field);
  const tick = vi.fn();
  const feedback = createTypingFeedback(tick);
  field.addEventListener("keydown", feedback.key);
  const key = (value: string, options: KeyboardEventInit = {}) =>
    field.dispatchEvent(new KeyboardEvent("keydown", { key: value, ...options }));
  return { field, tick, feedback, key };
}
test("Arabic and Latin letters, numbers and deletion sound without reading the input value", () => {
  const { key, tick } = fixture("password");
  for (const value of ["ع", "a", "1", " ", "Backspace", "Delete"]) {
    key(value);
    vi.advanceTimersByTime(100);
  }
  expect(tick).toHaveBeenCalledTimes(6);
});
test("keyboard-wedge scans stay silent and subsequent human typing resumes", () => {
  const { key, tick } = fixture();
  for (const value of "880123456789") {
    key(value);
    vi.advanceTimersByTime(8);
  }
  key("Enter");
  vi.advanceTimersByTime(100);
  expect(tick).not.toHaveBeenCalled();
  key("ع");
  vi.advanceTimersByTime(100);
  expect(tick).toHaveBeenCalledTimes(1);
});
test("two rapid human keys retain their ticks, sustained scanner bursts need no Enter", () => {
  const { key, tick } = fixture();
  key("a");
  vi.advanceTimersByTime(35);
  key("b");
  vi.advanceTimersByTime(100);
  expect(tick).toHaveBeenCalledTimes(2);
  for (const value of "123456") {
    key(value);
    vi.advanceTimersByTime(15);
  }
  vi.advanceTimersByTime(100);
  expect(tick).toHaveBeenCalledTimes(2);
});
test("shortcuts, arrows, repeated keys, composition and read-only fields remain silent", () => {
  const { field, key, tick } = fixture();
  key("v", { ctrlKey: true });
  key("a", { altKey: true });
  key("x", { metaKey: true });
  key("x", { repeat: true });
  key("ع", { isComposing: true });
  key("ArrowLeft");
  field.readOnly = true;
  key("x");
  vi.advanceTimersByTime(100);
  expect(tick).not.toHaveBeenCalled();
});
test("clearing on focus loss or unmount cancels queued feedback", () => {
  const { key, tick, feedback } = fixture();
  key("x");
  feedback.clear();
  vi.advanceTimersByTime(100);
  expect(tick).not.toHaveBeenCalled();
});
test("textarea and nested editable text work; non-text input controls remain silent", () => {
  const tick = vi.fn();
  const feedback = createTypingFeedback(tick);
  const textarea = document.createElement("textarea");
  const editable = document.createElement("div");
  editable.setAttribute("contenteditable", "true");
  const span = document.createElement("span");
  editable.append(span);
  document.body.append(textarea, editable);
  document.body.addEventListener("keydown", feedback.key);
  for (const field of [textarea, span]) {
    field.dispatchEvent(new KeyboardEvent("keydown", { key: "ع", bubbles: true }));
    vi.advanceTimersByTime(100);
  }
  document.body.removeEventListener("keydown", feedback.key);
  expect(tick).toHaveBeenCalledTimes(2);
  const range = fixture("range");
  range.key("1");
  vi.advanceTimersByTime(100);
  expect(range.tick).not.toHaveBeenCalled();
});
