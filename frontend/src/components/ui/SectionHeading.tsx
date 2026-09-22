import type { ReactNode } from "react";

type SectionHeadingProps = {
  className: string;
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
};

/** Keeps card titles, descriptions and optional trailing controls consistent. */
export function SectionHeading({
  className,
  icon,
  title,
  description,
  children,
}: SectionHeadingProps) {
  return (
    <div className={className}>
      {icon}
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {children}
    </div>
  );
}
