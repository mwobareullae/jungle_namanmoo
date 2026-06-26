import { useEffect, useState } from "react";

export function useElapsedSeconds(active: boolean) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (!active) {
      return undefined;
    }

    const timerId = window.setInterval(() => {
      setElapsedSeconds((currentSeconds) => currentSeconds + 1);
    }, 1000);

    return () => {
      window.clearInterval(timerId);
    };
  }, [active]);

  if (!active) {
    return 0;
  }

  return elapsedSeconds;
}
