import { helpSections } from "../content/helpContent";
import { replayOnboarding } from "../utils/onboarding";

export function HelpPage() {
  return (
    <div className="stack-lg">
      <div className="page-header">
        <div>
          <h1>Help</h1>
          <p className="helper-text">Offline reference material for uploading, reports, retention, telemetry, and troubleshooting.</p>
        </div>
        <button type="button" className="button-muted" onClick={() => replayOnboarding()}>
          Replay walkthrough
        </button>
      </div>

      <div className="card stack-md">
        {helpSections.map((section) => (
          <section key={section.id} id={section.id} className="help-section">
            <h2>{section.title}</h2>
            <p className="helper-text">{section.summary}</p>
            <ul className="help-list">
              {section.bullets.map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
