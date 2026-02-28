// Mock FEMA Form 009-0-3 template
export const femaForm = {
  id: 'fema-009-0-3',
  title: 'FEMA Disaster Aid Form',
  subtitle: 'Form 009-0-3',
  agency: 'FEMA',
  questions: [
    {
      id: 1,
      label: 'What is your full legal name?',
      fieldName: 'applicant_name',
      type: 'text',
    },
    {
      id: 2,
      label: 'What is your date of birth?',
      fieldName: 'date_of_birth',
      type: 'date',
    },
    {
      id: 3,
      label: 'What is your Social Security Number?',
      fieldName: 'ssn',
      type: 'ssn',
      sensitive: true,
    },
    {
      id: 4,
      label: 'What is your current mailing address?',
      fieldName: 'mailing_address',
      type: 'address',
    },
    {
      id: 5,
      label: 'What is your phone number?',
      fieldName: 'phone_number',
      type: 'phone',
    },
    {
      id: 6,
      label: 'What type of disaster affected you?',
      fieldName: 'disaster_type',
      type: 'text',
    },
    {
      id: 7,
      label: 'What is the address of the damaged property?',
      fieldName: 'damaged_property_address',
      type: 'address',
    },
    {
      id: 8,
      label: 'Do you have insurance coverage for the damaged property?',
      fieldName: 'has_insurance',
      type: 'yes_no',
    },
  ],
};

export const formTemplates = [
  {
    id: 'fema-009-0-3',
    name: 'FEMA Disaster Aid',
    agency: 'FEMA',
    description: 'Application for federal disaster assistance',
    icon: '🏠',
    color: '#2a7886',
  },
  {
    id: 'housing-app',
    name: 'Housing Application',
    agency: 'HUD',
    description: 'Public housing assistance application',
    icon: '🏢',
    color: '#5b4db8',
  },
  {
    id: 'medical-intake',
    name: 'Medical Intake',
    agency: 'Health',
    description: 'Patient intake and medical history form',
    icon: '🏥',
    color: '#c0392b',
  },
];
