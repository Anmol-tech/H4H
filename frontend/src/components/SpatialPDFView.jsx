/**
 * SpatialPDFView — shows the FEMA form as a 3D spatial card using WebSpatial.
 * In normal browser: renders as a 3D tilting card with depth.
 * In visionOS simulator (XR_ENV=avp): the card and fields float in real 3D space.
 */
import { useRef, useCallback } from 'react';
import './SpatialPDFView.css';

const FEMA_QUESTIONS = [
  { id: 1, label: 'What is your full legal name?', fieldName: 'applicant_name' },
  { id: 2, label: 'What is your date of birth?', fieldName: 'date_of_birth' },
  { id: 3, label: 'What is your Social Security Number?', fieldName: 'ssn' },
  { id: 4, label: 'What is your current mailing address?', fieldName: 'mailing_address' },
  { id: 5, label: 'What is your phone number?', fieldName: 'phone_number' },
  { id: 6, label: 'What type of disaster affected you?', fieldName: 'disaster_type' },
  { id: 7, label: 'What is the address of the damaged property?', fieldName: 'damaged_property_address' },
  { id: 8, label: 'Do you have insurance coverage for the damaged property?', fieldName: 'has_insurance' },
];

export default function SpatialPDFView({ answers = {}, currentIndex = 0 }) {
  const questions = FEMA_QUESTIONS;
  const cardRef = useRef(null);

  const handlePointerMove = useCallback((e) => {
    const card = cardRef.current;
    if (!card) return;
    // CRITICAL: cancel the CSS animation — CSS animations override inline styles in the cascade.
    // Once the user moves, we take over with JS.
    if (card.style.animation !== 'none') {
      card.style.animation = 'none';
    }
    card.style.transition = 'none';

    // Track position relative to the whole viewport for a wider tilt range
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const clientX = e.clientX ?? e.touches?.[0]?.clientX;
    const clientY = e.clientY ?? e.touches?.[0]?.clientY;
    if (clientX == null || clientY == null) return;

    const x = clientX / vw;          // 0 (left) → 1 (right)
    const y = clientY / vh;          // 0 (top)  → 1 (bottom)
    const rotateX = (0.5 - y) * 20; // tilt up/down  ±10 deg
    const rotateY = (x - 0.5) * 28; // tilt left/right ±14 deg
    card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateZ(24px) scale(1.01)`;
  }, []);

  const handlePointerLeave = useCallback(() => {
    const card = cardRef.current;
    if (!card) return;
    card.style.transition = 'transform 0.6s cubic-bezier(0.23, 1, 0.32, 1)';
    card.style.transform = 'perspective(1000px) rotateX(4deg) rotateY(-3deg) translateZ(0px)';
  }, []);

  return (
    <div
      className="spatial-page"
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
    >
      <div className="spatial-header">
        <h1 className="spatial-title">FormWhisper</h1>
        <p className="spatial-subtitle">3D Spatial Form View</p>
        <p className="spatial-hint">
          📱 In visionOS: fields float in 3D space &nbsp;|&nbsp; 🖥️ In browser: interactive flat view
        </p>
      </div>

      {/* Main form card — spatialized with enable-xr */}
      <div
        className="spatial-form-card"
        enable-xr=""
        ref={cardRef}
      >
        {/* PDF Header */}
        <div className="spatial-form-header">
          <div className="spatial-agency-badge">FEMA</div>
          <div>
            <h2>FEMA Disaster Aid Form</h2>
            <p>Form 009-0-3</p>
          </div>
        </div>

        {/* Form Fields — each field is individually spatialized */}
        <div className="spatial-fields">
          {questions.map((q, i) => {
            const isFilled = !!answers[q.fieldName];
            const isActive = i === currentIndex;

            return (
              <div
                key={q.id}
                className={`spatial-field ${isActive ? 'active' : ''} ${isFilled ? 'filled' : ''}`}
                enable-xr=""
              >
                <span className="spatial-field-number">{q.id}</span>
                <div className="spatial-field-content">
                  <span className="spatial-field-label">{q.label}</span>
                  {isFilled && (
                    <span className="spatial-field-value">{answers[q.fieldName]}</span>
                  )}
                  {isActive && !isFilled && (
                    <span className="spatial-field-active-badge">▶ Current</span>
                  )}
                </div>
                <span className={`spatial-field-status ${isFilled ? 'done' : isActive ? 'now' : 'empty'}`}>
                  {isFilled ? '✓' : isActive ? '●' : '○'}
                </span>
              </div>
            );
          })}
        </div>

        {/* Progress */}
        <div className="spatial-progress-bar">
          <div
            className="spatial-progress-fill"
            style={{ width: `${(Object.keys(answers).length / questions.length) * 100}%` }}
          />
        </div>
        <p className="spatial-progress-label">
          {Object.keys(answers).length} of {questions.length} fields completed
        </p>
      </div>
    </div>
  );
}
