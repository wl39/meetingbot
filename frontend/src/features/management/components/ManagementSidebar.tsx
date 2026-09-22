import { HardDrive } from "lucide-react";
import type { SettingsPath } from "../../../workspace/navigation";
import { sections } from "../sections";

type ManagementSidebarProps = {
  sectionPath: SettingsPath;
  navigate: (path: SettingsPath) => void;
};

export default function ManagementSidebar({
  sectionPath,
  navigate,
}: ManagementSidebarProps) {
  return (
    <aside className="management-sidebar">
      <div className="management-sidebar-title">설정 및 관리</div>
      <nav aria-label="관리 메뉴">
        {sections.map((item) => (
          <button
            key={item.path}
            aria-current={sectionPath === item.path ? "page" : undefined}
            className={sectionPath === item.path ? "selected" : ""}
            onClick={() => navigate(item.path)}
          >
            <item.Icon size={19} />
            <span>
              {item.label}
              <small>{item.description}</small>
            </span>
          </button>
        ))}
      </nav>
      <div className="management-sidebar-note">
        <HardDrive size={20} />
        <strong>서비스 운영 관리</strong>
        <p>
          문서와 회의 기록 서비스를
          <br />
          안정적으로 운영하기 위한 설정입니다.
        </p>
      </div>
    </aside>
  );
}
