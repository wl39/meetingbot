import type { ReactNode } from "react";
import { X } from "lucide-react";

type FeedbackMessageProps = {
  className: string;
  tone?: "error" | "status";
  icon?: ReactNode;
  children: ReactNode;
  onDismiss?: () => void;
  dismissLabel?: string;
  dismissContent?: ReactNode;
};

/** Shared announcement and dismiss behavior; feature styles remain local. */
export function FeedbackMessage({
  className,
  tone = "status",
  icon,
  children,
  onDismiss,
  dismissLabel = "알림 닫기",
  dismissContent = <X size={17} />,
}: FeedbackMessageProps) {
  return (
    <div className={className} role={tone === "error" ? "alert" : "status"}>
      {icon}
      {children}
      {onDismiss && (
        <button type="button" aria-label={dismissLabel} onClick={onDismiss}>
          {dismissContent}
        </button>
      )}
    </div>
  );
}
