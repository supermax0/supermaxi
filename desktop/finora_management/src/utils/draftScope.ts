export const draftScope = (node: Element | null) =>
  node?.closest('form,[role="dialog"],[data-draft-scope]') ?? null;
