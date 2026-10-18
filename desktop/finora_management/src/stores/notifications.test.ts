import { useNotifications } from "./notifications";
beforeEach(() => useNotifications.getState().clear());
it("removes revoked HR alerts and their unread badge without deleting connection events", () => {
  const state = useNotifications.getState();
  state.add({ tone: "warning", title: "الاتصال انقطع", body: "" });
  state.replaceHR([{ group: "hr", key: "leave:1", tone: "warning", title: "إجازة", body: "", at: 10 }]);
  expect(useNotifications.getState().unread).toBe(2);
  state.replaceHR([]);
  expect(useNotifications.getState().items.map((i) => i.title)).toEqual(["الاتصال انقطع"]);
  expect(useNotifications.getState().unread).toBe(1);
});
it("preserves read status through polling and flags newly actionable requests", () => {
  const state = useNotifications.getState();
  const item = {
    group: "hr" as const,
    key: "leave:1",
    tone: "warning" as const,
    title: "إجازة",
    body: "",
    at: 10,
  };
  state.replaceHR([item]);
  state.markAllRead();
  state.replaceHR([{ ...item, body: "تحديث" }]);
  expect(useNotifications.getState().unread).toBe(0);
  state.replaceHR([item, { ...item, key: "correction:1" }]);
  expect(useNotifications.getState().unread).toBe(1);
});
