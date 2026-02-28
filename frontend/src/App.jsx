import { useState } from 'react';
import Header from './components/Header';
import HomePage from './components/HomePage';
import FormSession from './components/FormSession';
import Sponsors from './components/Sponsors';
import './App.css';

function App() {
  const [view, setView] = useState('home'); // home | session
  const [activeTemplate, setActiveTemplate] = useState(null);

  const handleSelectTemplate = (templateId) => {
    setActiveTemplate(templateId);
    setView('session');
  };

  const handleLogoClick = () => {
    setView('home');
    setActiveTemplate(null);
  };

  const getSessionName = () => {
    if (activeTemplate === 'fema-009-0-3') return 'FEMA Form 009-0-3';
    if (activeTemplate === 'housing-app') return 'Housing Application';
    if (activeTemplate === 'medical-intake') return 'Medical Intake Form';
    return null;
  };

  return (
    <>
      <Header
        activeSession={view === 'session' ? getSessionName() : null}
        onLogoClick={handleLogoClick}
      />

      {view === 'home' ? (
        <>
          <HomePage onSelectTemplate={handleSelectTemplate} />
          <Sponsors />
        </>
      ) : (
        <FormSession />
      )}
    </>
  );
}

export default App;
