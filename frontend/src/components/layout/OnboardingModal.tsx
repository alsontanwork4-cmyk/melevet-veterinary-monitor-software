type OnboardingModalProps = {
  isOpen: boolean;
  onClose: () => void;
};

const steps = [
  {
    title: "Patients overview",
    body: "Use Patients as the main worklist for saved encounters, upload history, and chart summaries.",
  },
  {
    title: "Uploading a snapshot",
    body: "Open Upload to stage a monitor snapshot, confirm discovery results, and save the encounter date.",
  },
  {
    title: "Reports and archived histories",
    body: "Saved encounter reports stay visible even after archival. Archived uploads show a download notice instead of live charts.",
  },
  {
    title: "Settings and telemetry",
    body: "Settings now manages retention, telemetry export, and database monitoring.",
  },
  {
    title: "Help page",
    body: "Open Help anytime for upload requirements, retention guidance, telemetry privacy notes, and troubleshooting steps.",
  },
];

export function OnboardingModal({ isOpen, onClose }: OnboardingModalProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-card onboarding-modal" role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
        <div className="row-between">
          <div>
            <p className="helper-text">First-Run Walkthrough</p>
            <h2 id="onboarding-title">Clinic setup overview</h2>
          </div>
          <button type="button" className="button-muted" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="stack-md">
          {steps.map((step, index) => (
            <div key={step.title} className="settings-threshold-card">
              <strong>{index + 1}. {step.title}</strong>
              <p className="helper-text">{step.body}</p>
            </div>
          ))}
        </div>
        <div className="row-between">
          <p className="helper-text">You can replay this walkthrough later from Help or Settings.</p>
          <button type="button" className="button-primary" onClick={onClose}>
            Finish walkthrough
          </button>
        </div>
      </section>
    </div>
  );
}
