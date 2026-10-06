import { forwardRef, useRef, useState, useImperativeHandle } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface PeekPasswordInputProps extends Omit<React.ComponentProps<"input">, "type" | "value" | "onChange"> {
  value: string;
  onChange: (value: string) => void;
}

/**
 * Input de senha que exibe o último caractere digitado por 1 segundo antes de mascarar.
 * Usa type="text" com mascaramento manual via •.
 */
const PeekPasswordInput = forwardRef<HTMLInputElement, PeekPasswordInputProps>(
  ({ value, onChange, className, ...props }, ref) => {
    const [peekLast, setPeekLast] = useState(false);
    const timerRef = useRef<ReturnType<typeof setTimeout>>();
    const innerRef = useRef<HTMLInputElement>(null);

    useImperativeHandle(ref, () => innerRef.current!);

    const displayValue =
      peekLast && value.length > 0
        ? "•".repeat(value.length - 1) + value[value.length - 1]
        : "•".repeat(value.length);

    function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
      const raw = e.target.value;

      // Count leading bullet chars to know how many original chars are kept
      let bulletCount = 0;
      while (bulletCount < raw.length && raw[bulletCount] === "•") bulletCount++;
      const tail = raw.slice(bulletCount);

      const newPassword = value.slice(0, bulletCount) + tail;
      const added = newPassword.length > value.length;

      onChange(newPassword);

      clearTimeout(timerRef.current);
      if (added) {
        setPeekLast(true);
        timerRef.current = setTimeout(() => setPeekLast(false), 1000);
      } else {
        setPeekLast(false);
      }
    }

    return (
      <Input
        {...props}
        ref={innerRef}
        type="text"
        inputMode="text"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        value={displayValue}
        onChange={handleChange}
        className={cn("tracking-widest", className)}
      />
    );
  },
);
PeekPasswordInput.displayName = "PeekPasswordInput";

export { PeekPasswordInput };
