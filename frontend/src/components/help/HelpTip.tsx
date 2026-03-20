import { Link } from "react-router-dom";

type HelpTipProps = {
  title: string;
  body: string;
  sectionId?: string;
};

export function HelpTip({ title, body, sectionId }: HelpTipProps) {
  return (
    <aside className="help-tip">
      <div>
        <strong>{title}</strong>
        <p className="helper-text">{body}</p>
      </div>
      <Link to={sectionId ? `/help#${sectionId}` : "/help"} className="text-button">
        Open Help
      </Link>
    </aside>
  );
}
