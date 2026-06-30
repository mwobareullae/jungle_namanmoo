type OriginalRuntime = Record<string, (...args: unknown[]) => void>;

export const callOriginal = (name: string, ...args: unknown[]) => {
  const handler = (window as unknown as OriginalRuntime)[name];
  handler?.(...args);
};
