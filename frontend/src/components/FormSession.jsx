import { useState } from 'react';
import { femaForm } from '../data/mockData';
import './FormSession.css';

// Mock answers for demo purposes
const MOCK_ANSWERS = {
    applicant_name: 'Sid Johnson',
    date_of_birth: 'March 15, 1990',
    ssn: '***-**-1234',
    mailing_address: '1234 Oak Street, Austin, TX 78701',
    phone_number: '(512) 555-0147',
    disaster_type: 'Hurricane',
    damaged_property_address: '1234 Oak Street, Austin, TX 78701',
    has_insurance: 'No',
};

export default function FormSession() {
    const [currentIndex, setCurrentIndex] = useState(0);
    const [answers, setAnswers] = useState({});
    const [phase, setPhase] = useState('asking'); // asking | confirming | complete
    const [isListening, setIsListening] = useState(false);

    const questions = femaForm.questions;
    const current = questions[currentIndex];
    const totalQuestions = questions.length;
    const progress = ((Object.keys(answers).length) / totalQuestions) * 100;

    const handleMicClick = () => {
        if (phase !== 'asking') return;
        setIsListening((prev) => {
            if (prev) {
                // Stop listening → show confirmation
                setPhase('confirming');
                return false;
            }
            // Start listening
            // Simulate stopping after 2 seconds
            setTimeout(() => {
                setIsListening(false);
                setPhase('confirming');
            }, 2000);
            return true;
        });
    };

    const handleConfirm = (confirmed) => {
        if (confirmed) {
            const mockAnswer = MOCK_ANSWERS[current.fieldName] || 'Sample Answer';
            setAnswers((prev) => ({ ...prev, [current.fieldName]: mockAnswer }));

            if (currentIndex < totalQuestions - 1) {
                setCurrentIndex((prev) => prev + 1);
                setPhase('asking');
            } else {
                setPhase('complete');
            }
        } else {
            // Retry
            setPhase('asking');
        }
    };

    const handleReplay = () => {
        // Would replay the audio question — for now it's a no-op
    };

    const handleNextField = () => {
        if (phase === 'asking') {
            // Simulate answering and go to confirm
            setPhase('confirming');
        }
    };

    const getMockAnswer = () => MOCK_ANSWERS[current?.fieldName] || 'Sample Answer';

    return (
        <div className="form-session">
            {/* Left: PDF Preview */}
            <div className="pdf-preview">
                <div className="pdf-document">
                    <div className="pdf-header">
                        <div className="pdf-agency-logo">{femaForm.agency}</div>
                        <div className="pdf-header-text">
                            <h2>{femaForm.title}</h2>
                            <p>{femaForm.subtitle}</p>
                        </div>
                    </div>

                    <p className="pdf-description">
                        The FEMA Disaster Aid application is used to apply for Individual Assistance
                        including housing assistance and other disaster-related needs. Complete all
                        applicable fields. Assistance is available regardless of immigration status.
                    </p>

                    <div className="pdf-fields">
                        {questions.map((q, i) => {
                            const isFilled = !!answers[q.fieldName];
                            const isActive = i === currentIndex && phase !== 'complete';
                            return (
                                <div
                                    key={q.id}
                                    className={`pdf-field ${isActive ? 'active' : ''} ${isFilled ? 'filled' : ''}`}
                                >
                                    <span className="pdf-field-number">{q.id}</span>
                                    <span className="pdf-field-label">{q.label}</span>
                                    {isFilled && (
                                        <span className="pdf-field-value">{answers[q.fieldName]}</span>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    <div className="pdf-footer">
                        <span>Disaster Aid Form</span>
                        <span>Page 1 of 1</span>
                    </div>
                </div>
            </div>

            {/* Right: Voice Panel */}
            <div className="voice-panel">
                {phase === 'complete' ? (
                    <div className="voice-complete">
                        <div className="complete-icon">
                            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                                <polyline points="20 6 9 17 4 12" />
                            </svg>
                        </div>
                        <h2 className="complete-title">Form Complete!</h2>
                        <p className="complete-subtitle">
                            All {totalQuestions} fields have been filled successfully.
                        </p>
                        <button className="download-btn">
                            <span style={{ marginRight: '0.5rem' }}>📄</span>
                            Download Filled PDF
                        </button>
                    </div>
                ) : phase === 'confirming' ? (
                    <div className="voice-confirmation">
                        <p className="voice-confirmation-heard">I heard:</p>
                        <p className="voice-confirmation-value">"{getMockAnswer()}"</p>
                        <p className="voice-confirmation-prompt">Is that correct?</p>
                        <div className="confirm-actions">
                            <button className="confirm-btn yes" onClick={() => handleConfirm(true)}>
                                ✓ Yes
                            </button>
                            <button className="confirm-btn no" onClick={() => handleConfirm(false)}>
                                ✗ No
                            </button>
                        </div>
                    </div>
                ) : (
                    <>
                        {/* Avatar */}
                        <div className="voice-avatar">
                            <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5">
                                <circle cx="12" cy="8" r="4" />
                                <path d="M6 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2" />
                            </svg>
                        </div>

                        <span className="voice-question-number">
                            Question {current.id}:
                        </span>

                        <h2 className="voice-question-text">{current.label}</h2>

                        <p className="voice-instruction">
                            {isListening ? 'Listening...' : 'Speak your answer now'}
                        </p>

                        {/* Mic Button */}
                        <div className="mic-button-wrapper">
                            <button
                                className={`mic-button ${isListening ? 'listening' : ''}`}
                                onClick={handleMicClick}
                                aria-label={isListening ? 'Stop recording' : 'Start recording'}
                            >
                                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                                    <line x1="12" y1="19" x2="12" y2="23" />
                                    <line x1="8" y1="23" x2="16" y2="23" />
                                </svg>
                            </button>
                            <div className="mic-pulse-ring"></div>
                            <div className="mic-pulse-ring"></div>
                            <div className="mic-pulse-ring"></div>
                        </div>

                        {/* Actions */}
                        <div className="voice-actions">
                            <button className="voice-action-btn" onClick={handleReplay}>
                                🔁 Replay Question
                            </button>
                            <button className="voice-action-btn primary" onClick={handleNextField}>
                                Next Field →
                            </button>
                        </div>
                    </>
                )}

                {/* Progress bar */}
                <div className="voice-progress">
                    <div className="voice-progress-fill" style={{ width: `${progress}%` }}></div>
                </div>
            </div>
        </div>
    );
}
