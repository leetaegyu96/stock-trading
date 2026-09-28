// 빈 상태는 "없습니다"로 끝내지 않고 **다음 행동**을 준다(SPEC §8.2).
import type { ReactNode } from "react";

export interface EmptyStateProps {
  title: string;
  desc: string;
  action?: ReactNode;
}

export function EmptyState({ title, desc, action }: EmptyStateProps) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      <p className="empty__desc">{desc}</p>
      {action}
    </div>
  );
}

export default EmptyState;
