export {};

declare global {
  interface Window {
    FinoraTime: { dateTime(value: string): string };
  }
}
