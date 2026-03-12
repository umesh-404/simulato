import React, { useState, useEffect } from 'react';
import { 
  Shield, Globe, MessageSquare, Cloud, Smartphone, Lock, 
  Search, FileText, AlertCircle, Users, Landmark, ChevronRight, 
  CheckCircle, ArrowRight, Cpu, Activity, User, Briefcase, MapPin,
  Bot, X, Printer, Download, ShieldCheck, Languages
} from 'lucide-react';

// --- EXPANDED MOCK DATABASE FOR SIMULATION ---
const schemesDatabase = [
  {
    id: 1,
    name: "Ayushman Bharat Yojana (PM-JAY)",
    description: "Health insurance coverage up to ₹5 lakh per family per year for secondary and tertiary care hospitalization.",
    eligibility: (data) => data.income <= 500000,
    tags: ["Health", "Low Income", "Central"],
    documents: ["Aadhar Card", "Income Certificate", "Ration Card"]
  },
  {
    id: 2,
    name: "PM-KISAN Samman Nidhi",
    description: "Income support of ₹6,000 per year in three equal installments to all landholding farmer families.",
    eligibility: (data) => data.occupation === 'farmer',
    tags: ["Agriculture", "Financial Support", "Central"],
    documents: ["Aadhar Card", "Land Ownership Papers", "Bank Account"]
  },
  {
    id: 3,
    name: "Sukanya Samriddhi Yojana",
    description: "A small savings scheme backed by the Government of India targeted at the parents of girl children.",
    eligibility: (data) => data.gender === 'female' && data.age <= 10,
    tags: ["Savings", "Girl Child", "Central"],
    documents: ["Birth Certificate", "Parents Aadhar", "Address Proof"]
  },
  {
    id: 4,
    name: "National Social Assistance Programme (NSAP)",
    description: "Financial assistance to the elderly, widows and persons with disabilities in the form of social pensions.",
    eligibility: (data) => data.age >= 60,
    tags: ["Pension", "Senior Citizen", "Central"],
    documents: ["Age Proof", "Aadhar Card", "BPL Card"]
  },
  {
    id: 5,
    name: "Stand Up India Scheme",
    description: "Bank loans between ₹10 lakh and ₹1 Crore to at least one SC/ST borrower and one woman borrower per bank branch.",
    eligibility: (data) => data.gender === 'female' || data.caste === 'SC' || data.caste === 'ST',
    tags: ["Business", "Empowerment", "Loan"],
    documents: ["Identity Proof", "Caste Certificate", "Business Plan"]
  },
  {
    id: 6,
    name: "Mudra Yojana (PMMY)",
    description: "Loans up to ₹10 lakh to non-corporate, non-farm small/micro enterprises.",
    eligibility: (data) => data.occupation === 'business' || data.occupation === 'unemployed',
    tags: ["Business", "Loan", "Central"],
    documents: ["Aadhar Card", "Business Registration", "Bank Statement"]
  },
  {
    id: 7,
    name: "Pradhan Mantri Ujjwala Yojana (PMUY)",
    description: "Provides LPG connections to women from Below Poverty Line (BPL) households.",
    eligibility: (data) => data.gender === 'female' && data.income <= 250000,
    tags: ["Women", "Subsidies", "Household"],
    documents: ["BPL Ration Card", "Aadhar Card", "Passport Size Photo"]
  },
  {
    id: 8,
    name: "Mahatma Gandhi National Rural Employment Guarantee Act (MGNREGA)",
    description: "Enhances livelihood security in rural areas by providing at least 100 days of guaranteed wage employment.",
    eligibility: (data) => data.location === 'Rural' && data.age >= 18 && (data.occupation === 'unemployed' || data.occupation === 'farmer'),
    tags: ["Employment", "Rural", "Wage"],
    documents: ["Job Card", "Aadhar Card", "Bank Account Details"]
  },
  {
    id: 9,
    name: "Pradhan Mantri Awas Yojana (PMAY)",
    description: "Aims to provide housing for all. Subsidies on home loans for first-time buyers in eligible income brackets.",
    eligibility: (data) => data.income <= 600000,
    tags: ["Housing", "Subsidy", "Urban/Rural"],
    documents: ["Aadhar Card", "Income Proof", "Bank Statement"]
  }
];

// --- MAIN APPLICATION COMPONENT ---
export default function App() {
  const [activeTab, setActiveTab] = useState('home');
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [language, setLanguage] = useState('English');

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-800 relative">
      {/* Navigation */}
      <nav className="bg-white shadow-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <div className="flex items-center cursor-pointer" onClick={() => setActiveTab('home')}>
              <Landmark className="h-8 w-8 text-indigo-600 mr-2" />
              <span className="font-bold text-xl tracking-tight text-slate-900">GovEligibility<span className="text-indigo-600">AI</span></span>
            </div>
            <div className="hidden md:flex items-center space-x-8">
              <button onClick={() => setActiveTab('home')} className={`text-sm font-medium ${activeTab === 'home' ? 'text-indigo-600' : 'text-slate-500 hover:text-indigo-600'}`}>Home</button>
              <button onClick={() => setActiveTab('finder')} className={`text-sm font-medium ${activeTab === 'finder' ? 'text-indigo-600' : 'text-slate-500 hover:text-indigo-600'}`}>AI Finder</button>
              <a href="#features" className="text-sm font-medium text-slate-500 hover:text-indigo-600">Features</a>
              
              {/* Language Selector */}
              <div className="relative group">
                <button className="flex items-center text-sm font-medium text-slate-500 hover:text-indigo-600">
                  <Languages className="h-4 w-4 mr-1" /> {language}
                </button>
                <div className="absolute right-0 mt-2 w-32 bg-white rounded-md shadow-lg py-1 z-50 hidden group-hover:block border border-slate-100">
                  {['English', 'Hindi (हिंदी)', 'Telugu (తెలుగు)'].map(lang => (
                    <button key={lang} onClick={() => setLanguage(lang)} className="block w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-indigo-50 hover:text-indigo-600">
                      {lang}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div>
              <button onClick={() => setActiveTab('finder')} className="bg-indigo-600 text-white px-5 py-2 rounded-lg font-medium hover:bg-indigo-700 transition-colors shadow-md hover:shadow-lg flex items-center">
                <Search className="h-4 w-4 mr-2" /> Find Schemes
              </button>
            </div>
          </div>
        </div>
      </nav>

      {/* Main Content Area */}
      {activeTab === 'home' ? (
        <>
          {/* Hero Section */}
          <section className="relative bg-gradient-to-br from-indigo-900 via-blue-800 to-indigo-700 text-white overflow-hidden">
            <div className="absolute inset-0 opacity-10 bg-[url('https://www.transparenttextures.com/patterns/cubes.png')]"></div>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24 relative z-10">
              <div className="grid md:grid-cols-2 gap-12 items-center">
                <div className="space-y-6">
                  <div className="inline-block bg-blue-500/30 border border-blue-400/50 backdrop-blur-sm rounded-full px-4 py-1.5 text-sm font-medium text-blue-100 mb-2 flex items-center w-fit">
                    <ShieldCheck className="h-4 w-4 mr-2 text-green-400" /> Secure & Encrypted
                  </div>
                  <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold leading-tight tracking-tight">
                    AI-Powered Government Scheme Eligibility Finder
                  </h1>
                  <p className="text-xl text-blue-100 max-w-lg leading-relaxed">
                    Revolutionizing how citizens discover and access public support — faster, smarter, and for everyone.
                  </p>
                  <div className="pt-4 flex flex-col sm:flex-row space-y-3 sm:space-y-0 sm:space-x-4">
                    <button onClick={() => setActiveTab('finder')} className="bg-white text-indigo-700 px-8 py-3.5 rounded-lg font-bold hover:bg-indigo-50 transition-colors shadow-lg flex items-center justify-center group">
                      Start Your Free Check <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform" />
                    </button>
                  </div>
                </div>
                <div className="hidden md:block relative">
                  <div className="absolute inset-0 bg-gradient-to-tr from-indigo-500 to-blue-400 rounded-2xl blur-2xl opacity-40 animate-pulse"></div>
                  <div className="bg-white/10 backdrop-blur-md border border-white/20 p-8 rounded-2xl shadow-2xl relative">
                    <div className="flex items-center space-x-4 mb-6">
                      <div className="w-12 h-12 bg-indigo-500 rounded-full flex items-center justify-center">
                        <Cpu className="text-white h-6 w-6" />
                      </div>
                      <div>
                        <h3 className="font-semibold text-lg">AI Matching Engine</h3>
                        <p className="text-blue-200 text-sm">Processing 10,000+ rules via NLP</p>
                      </div>
                    </div>
                    <div className="space-y-4">
                      <div className="h-2 bg-white/20 rounded-full overflow-hidden"><div className="w-3/4 h-full bg-blue-400 rounded-full"></div></div>
                      <div className="h-2 bg-white/20 rounded-full overflow-hidden"><div className="w-1/2 h-full bg-blue-400 rounded-full"></div></div>
                      <div className="h-2 bg-white/20 rounded-full overflow-hidden"><div className="w-5/6 h-full bg-blue-400 rounded-full"></div></div>
                    </div>
                    <div className="mt-8 bg-white/5 rounded-xl p-4 border border-white/10">
                      <div className="flex justify-between items-center text-sm">
                        <span>Profile Match Complete</span>
                        <span className="text-green-400 flex items-center"><CheckCircle className="h-4 w-4 mr-1"/> 100%</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* How It Works */}
          <section className="py-20 bg-slate-50">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="text-center mb-16">
                <h2 className="text-3xl font-bold text-slate-900 sm:text-4xl">How It Works</h2>
                <p className="mt-4 text-lg text-slate-600">From a single input to a full personalised action plan — in under a minute.</p>
              </div>
              
              <div className="relative">
                <div className="hidden md:block absolute top-1/2 left-0 right-0 h-1 bg-indigo-200 -translate-y-1/2 z-0"></div>
                <div className="grid md:grid-cols-4 gap-8 relative z-10">
                  {[
                    { step: 1, title: "Enter Details", desc: "Basic personal inputs (Age, income, occupation)" },
                    { step: 2, title: "AI Interprets", desc: "NLP analyzes inputs intelligently against scheme rules" },
                    { step: 3, title: "Compare Profiles", desc: "Matching engine cross-references millions of data points" },
                    { step: 4, title: "Show Matches", desc: "Instant personalised scheme list with documents & steps" }
                  ].map((item) => (
                    <div key={item.step} className="bg-white rounded-2xl p-6 shadow-lg border border-slate-100 text-center relative flex flex-col items-center">
                      <div className="w-12 h-12 bg-indigo-600 text-white rounded-full flex items-center justify-center font-bold text-xl mb-4 shadow-md ring-4 ring-white">
                        {item.step}
                      </div>
                      <h3 className="text-lg font-bold text-slate-900 mb-2">{item.title}</h3>
                      <p className="text-slate-500 text-sm">{item.desc}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>

          {/* Key Features & Technologies */}
          <section className="py-20 bg-white" id="features">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="text-center mb-16">
                <h2 className="text-3xl font-bold text-slate-900 sm:text-4xl">Key Features & Technologies</h2>
                <p className="mt-4 text-lg text-slate-600">Powered by advanced AI, ML, and NLP technologies.</p>
              </div>
              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
                {[
                  { icon: User, title: "Personalised Recommendations", desc: "Tailored scheme matches based on individual citizen profiles." },
                  { icon: Globe, title: "Multi-Language Support", desc: "Accessible in regional languages for wider reach and inclusivity." },
                  { icon: MessageSquare, title: "Chatbot Assistance", desc: "Guided, conversational experience — voice and text input support." },
                  { icon: Cloud, title: "Auto-Updated Database", desc: "Always current — powered by cloud APIs and real-time government data." },
                  { icon: Smartphone, title: "Mobile-First Design", desc: "Optimised for smartphones — works seamlessly even on low-end devices." },
                  { icon: Lock, title: "Secure & Encrypted", desc: "End-to-end data security protects citizen information and privacy." }
                ].map((feature, idx) => (
                  <div key={idx} className="flex flex-col p-6 bg-slate-50 rounded-2xl hover:bg-indigo-50 transition-colors border border-transparent hover:border-indigo-100">
                    <div className="w-14 h-14 bg-white rounded-xl shadow-sm border border-slate-200 flex items-center justify-center mb-6 text-indigo-600">
                      <feature.icon className="h-7 w-7" />
                    </div>
                    <h3 className="text-xl font-bold text-slate-900 mb-2">{feature.title}</h3>
                    <p className="text-slate-600 flex-grow">{feature.desc}</p>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* Benefits Section */}
          <section className="py-20 bg-slate-900 text-white" id="benefits">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="text-center mb-16">
                <h2 className="text-3xl font-bold sm:text-4xl">Benefits & Impact</h2>
                <p className="mt-4 text-lg text-slate-400">Creating a win-win ecosystem for the nation.</p>
              </div>
              <div className="grid md:grid-cols-2 gap-12">
                <div className="bg-slate-800 rounded-3xl p-10 border border-slate-700">
                  <div className="flex items-center mb-8">
                    <User className="h-10 w-10 text-blue-400 mr-4" />
                    <h3 className="text-2xl font-bold">For Citizens</h3>
                  </div>
                  <ul className="space-y-4">
                    {['Quick access to the right schemes', 'Saves time, reduces confusion', 'Empowers rural populations', 'Eliminates intermediaries'].map((item, i) => (
                      <li key={i} className="flex items-center text-slate-300">
                        <CheckCircle className="h-5 w-5 text-blue-400 mr-3 flex-shrink-0" />
                        <span className="text-lg">{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="bg-slate-800 rounded-3xl p-10 border border-slate-700">
                  <div className="flex items-center mb-8">
                    <Landmark className="h-10 w-10 text-emerald-400 mr-4" />
                    <h3 className="text-2xl font-bold">For Government</h3>
                  </div>
                  <ul className="space-y-4">
                    {['Higher scheme utilisation', 'Better welfare delivery', 'Improved digital governance', 'Data-driven policy planning'].map((item, i) => (
                      <li key={i} className="flex items-center text-slate-300">
                        <CheckCircle className="h-5 w-5 text-emerald-400 mr-3 flex-shrink-0" />
                        <span className="text-lg">{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          </section>
        </>
      ) : (
        /* The Interactive App Section */
        <EligibilityApp language={language} />
      )}

      {/* Footer */}
      <footer className="bg-white border-t border-slate-200 py-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col md:flex-row justify-between items-center">
            <div className="flex items-center mb-6 md:mb-0">
               <Landmark className="h-6 w-6 text-indigo-600 mr-2" />
               <span className="font-bold text-lg text-slate-900">GovEligibilityAI</span>
            </div>
            <div className="text-sm text-slate-500 text-center md:text-left mb-6 md:mb-0">
              <p>Project by Batch-12: J.Umesh Chandra, J.Pavan Venkat, A.Venkat Karthik, T.Kamal Hussain</p>
            </div>
            <div className="text-sm text-slate-400">
              © {new Date().getFullYear()} All rights reserved.
            </div>
          </div>
        </div>
      </footer>

      {/* Floating Chatbot Widget */}
      <div className="fixed bottom-6 right-6 z-50">
        {isChatOpen ? (
          <div className="bg-white w-80 rounded-2xl shadow-2xl border border-slate-200 overflow-hidden flex flex-col h-96 animate-in slide-in-from-bottom-5">
            <div className="bg-indigo-600 text-white p-4 flex justify-between items-center">
              <div className="flex items-center">
                <Bot className="h-5 w-5 mr-2" />
                <span className="font-semibold">AI Assistant</span>
              </div>
              <button onClick={() => setIsChatOpen(false)} className="text-indigo-200 hover:text-white">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="flex-1 p-4 bg-slate-50 overflow-y-auto space-y-4 text-sm">
              <div className="bg-white p-3 rounded-lg rounded-tl-none border border-slate-100 text-slate-700 shadow-sm w-5/6">
                Namaste! 🙏 I'm your AI guide. Need help finding which government schemes you qualify for?
              </div>
              <div className="bg-white p-3 rounded-lg rounded-tl-none border border-slate-100 text-slate-700 shadow-sm w-5/6">
                You can type your query in English, Hindi, or Telugu! For example: "I am a 30 year old farmer from AP."
              </div>
            </div>
            <div className="p-3 bg-white border-t border-slate-200">
              <div className="relative">
                <input 
                  type="text" 
                  placeholder="Type your message..." 
                  className="w-full pl-4 pr-10 py-2 border border-slate-300 rounded-full focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 text-sm"
                />
                <button className="absolute right-2 top-1.5 text-indigo-600 p-1 rounded-full hover:bg-indigo-50">
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        ) : (
          <button 
            onClick={() => setIsChatOpen(true)} 
            className="bg-indigo-600 text-white p-4 rounded-full shadow-2xl hover:bg-indigo-700 hover:scale-110 transition-all flex items-center justify-center group"
          >
            <MessageSquare className="h-6 w-6" />
            <span className="max-w-0 overflow-hidden group-hover:max-w-xs transition-all duration-300 ease-in-out whitespace-nowrap pl-0 group-hover:pl-2 font-medium">
              Ask AI Assistant
            </span>
          </button>
        )}
      </div>
    </div>
  );
}

// --- INTERACTIVE ELIGIBILITY FINDER COMPONENT ---
function EligibilityApp({ language }) {
  const [step, setStep] = useState(1);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [results, setResults] = useState([]);
  
  const [formData, setFormData] = useState({
    state: 'Andhra Pradesh',
    age: '',
    gender: '',
    income: '',
    occupation: '',
    caste: 'General',
    location: 'Urban'
  });

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleNext = () => {
    if (step < 2) setStep(step + 1);
    else analyzeData();
  };

  const analyzeData = () => {
    setIsAnalyzing(true);
    setStep(3);
    
    // Simulate AI processing time
    setTimeout(() => {
      const parsedData = {
        ...formData,
        age: parseInt(formData.age) || 0,
        income: parseInt(formData.income) || 0
      };
      
      const matchedSchemes = schemesDatabase.filter(scheme => scheme.eligibility(parsedData));
      setResults(matchedSchemes);
      setIsAnalyzing(false);
      setStep(4);
    }, 3000);
  };

  const resetForm = () => {
    setStep(1);
    setFormData({ state: 'Andhra Pradesh', age: '', gender: '', income: '', occupation: '', caste: 'General', location: 'Urban' });
    setResults([]);
  };

  const printResults = () => {
    window.print();
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-12 min-h-[80vh]">
      
      {/* App Header */}
      <div className="text-center mb-10 print:hidden">
        <h2 className="text-3xl font-bold text-slate-900">
          {language === 'Hindi (हिंदी)' ? 'अपनी योजनाएं खोजें' : 'Discover Your Benefits'}
        </h2>
        <p className="mt-2 text-slate-600">Our AI will match your profile with hundreds of central and state government schemes instantly.</p>
        
        <div className="mt-4 inline-flex items-center text-xs font-medium text-green-700 bg-green-50 px-3 py-1.5 rounded-full border border-green-200">
          <ShieldCheck className="h-4 w-4 mr-1.5" /> 256-bit Encryption • Data is never saved to servers
        </div>
      </div>

      {/* Progress Bar */}
      {step < 4 && (
        <div className="mb-8 print:hidden">
          <div className="flex justify-between mb-2">
            <span className={`text-sm font-medium ${step >= 1 ? 'text-indigo-600' : 'text-slate-400'}`}>Personal Details</span>
            <span className={`text-sm font-medium ${step >= 2 ? 'text-indigo-600' : 'text-slate-400'}`}>Socio-Economic Info</span>
            <span className={`text-sm font-medium ${step >= 3 ? 'text-indigo-600' : 'text-slate-400'}`}>AI Analysis</span>
          </div>
          <div className="h-2 w-full bg-slate-200 rounded-full overflow-hidden">
            <div 
              className="h-full bg-indigo-600 transition-all duration-500 ease-in-out relative"
              style={{ width: `${(step / 3) * 100}%` }}
            >
              <div className="absolute inset-0 bg-white/20 animate-[shimmer_2s_infinite]"></div>
            </div>
          </div>
        </div>
      )}

      {/* Form Area */}
      <div className="bg-white rounded-2xl shadow-xl border border-slate-100 overflow-hidden print:shadow-none print:border-none">
        
        {/* Step 1: Personal Details */}
        {step === 1 && (
          <div className="p-8">
            <h3 className="text-xl font-bold text-slate-800 mb-6 flex items-center">
              <User className="mr-2 h-5 w-5 text-indigo-500" /> Basic Information
            </h3>
            <div className="grid md:grid-cols-2 gap-6">
              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-slate-700 mb-2">State / Union Territory</label>
                <select 
                  name="state" 
                  value={formData.state} 
                  onChange={handleInputChange}
                  className="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-shadow bg-white"
                >
                  <option value="Andhra Pradesh">Andhra Pradesh</option>
                  <option value="Telangana">Telangana</option>
                  <option value="Karnataka">Karnataka</option>
                  <option value="Maharashtra">Maharashtra</option>
                  <option value="Uttar Pradesh">Uttar Pradesh</option>
                  <option value="Other">Other State</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Age</label>
                <input 
                  type="number" 
                  name="age" 
                  value={formData.age} 
                  onChange={handleInputChange}
                  className="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-shadow"
                  placeholder="e.g. 35"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Gender</label>
                <select 
                  name="gender" 
                  value={formData.gender} 
                  onChange={handleInputChange}
                  className="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-shadow bg-white"
                >
                  <option value="">Select Gender</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-slate-700 mb-2">Location Type</label>
                <div className="flex space-x-4">
                  <label className={`flex-1 flex items-center justify-center p-4 rounded-xl border-2 cursor-pointer transition-all ${formData.location === 'Urban' ? 'border-indigo-600 bg-indigo-50' : 'border-slate-200 hover:border-slate-300'}`}>
                    <input type="radio" name="location" value="Urban" checked={formData.location === 'Urban'} onChange={handleInputChange} className="hidden" />
                    <MapPin className={`h-5 w-5 mr-2 ${formData.location === 'Urban' ? 'text-indigo-600' : 'text-slate-400'}`} />
                    <span className={formData.location === 'Urban' ? 'font-semibold text-indigo-700' : 'text-slate-600'}>Urban</span>
                  </label>
                  <label className={`flex-1 flex items-center justify-center p-4 rounded-xl border-2 cursor-pointer transition-all ${formData.location === 'Rural' ? 'border-indigo-600 bg-indigo-50' : 'border-slate-200 hover:border-slate-300'}`}>
                    <input type="radio" name="location" value="Rural" checked={formData.location === 'Rural'} onChange={handleInputChange} className="hidden" />
                    <Cloud className={`h-5 w-5 mr-2 ${formData.location === 'Rural' ? 'text-indigo-600' : 'text-slate-400'}`} />
                    <span className={formData.location === 'Rural' ? 'font-semibold text-indigo-700' : 'text-slate-600'}>Rural</span>
                  </label>
                </div>
              </div>
            </div>
            <div className="mt-8 flex justify-end">
              <button 
                onClick={handleNext}
                disabled={!formData.age || !formData.gender}
                className="bg-indigo-600 text-white px-8 py-3 rounded-lg font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50 flex items-center"
              >
                Next Step <ChevronRight className="ml-2 h-5 w-5" />
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Socio-Economic */}
        {step === 2 && (
          <div className="p-8">
            <h3 className="text-xl font-bold text-slate-800 mb-6 flex items-center">
              <Briefcase className="mr-2 h-5 w-5 text-indigo-500" /> Socio-Economic Details
            </h3>
            <div className="grid md:grid-cols-2 gap-6">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Annual Family Income (₹)</label>
                <input 
                  type="number" 
                  name="income" 
                  value={formData.income} 
                  onChange={handleInputChange}
                  className="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-shadow"
                  placeholder="e.g. 250000"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Occupation / Status</label>
                <select 
                  name="occupation" 
                  value={formData.occupation} 
                  onChange={handleInputChange}
                  className="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-shadow bg-white"
                >
                  <option value="">Select Occupation</option>
                  <option value="farmer">Farmer / Agriculture</option>
                  <option value="student">Student</option>
                  <option value="business">Small Business / Self-Employed</option>
                  <option value="salaried">Salaried Employee</option>
                  <option value="unemployed">Unemployed / Daily Wage</option>
                </select>
              </div>
              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-slate-700 mb-2">Social Category</label>
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                  {['General', 'OBC', 'SC', 'ST', 'Minority'].map(caste => (
                     <label key={caste} className={`flex items-center justify-center p-3 rounded-xl border cursor-pointer transition-all ${formData.caste === caste ? 'border-indigo-600 bg-indigo-50 text-indigo-700 font-semibold shadow-sm' : 'border-slate-200 hover:border-slate-300 text-slate-600'}`}>
                       <input type="radio" name="caste" value={caste} checked={formData.caste === caste} onChange={handleInputChange} className="hidden" />
                       {caste}
                     </label>
                  ))}
                </div>
              </div>
            </div>
            <div className="mt-10 flex justify-between items-center">
              <button 
                onClick={() => setStep(1)}
                className="text-slate-600 px-6 py-3 rounded-lg font-medium hover:bg-slate-100 transition-colors"
              >
                Back
              </button>
              <button 
                onClick={handleNext}
                disabled={!formData.income || !formData.occupation}
                className="bg-indigo-600 text-white px-8 py-3 rounded-lg font-medium hover:bg-indigo-700 transition-colors shadow-lg disabled:opacity-50 flex items-center"
              >
                Analyze Matches <Activity className="ml-2 h-5 w-5" />
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Analyzing (AI Simulation) */}
        {step === 3 && (
          <div className="p-16 flex flex-col items-center justify-center text-center">
            <div className="relative mb-8">
              <div className="absolute inset-0 bg-indigo-400 rounded-full blur-xl opacity-50 animate-pulse"></div>
              <div className="h-24 w-24 bg-white rounded-full shadow-2xl flex items-center justify-center relative z-10">
                <Cpu className="h-10 w-10 text-indigo-600 animate-bounce" />
              </div>
            </div>
            <h3 className="text-2xl font-bold text-slate-800 mb-2">AI is analyzing your profile...</h3>
            <p className="text-slate-500 max-w-md">Scanning across hundreds of central and state databases via API, checking rule logic and eligibility criteria.</p>
            
            <div className="w-full max-w-xs mt-8 space-y-4 text-left text-sm text-slate-500 font-medium">
              <div className="flex items-center"><CheckCircle className="h-4 w-4 text-green-500 mr-2" /> Demographics & Location verified</div>
              <div className="flex items-center"><CheckCircle className="h-4 w-4 text-green-500 mr-2" /> Cross-referencing income brackets</div>
              <div className="flex items-center opacity-70 animate-pulse"><Activity className="h-4 w-4 text-indigo-500 mr-2" /> Compiling application workflows...</div>
            </div>
          </div>
        )}

        {/* Step 4: Results */}
        {step === 4 && (
          <div className="p-8 bg-slate-50 print:bg-white print:p-0">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
              <div>
                <h3 className="text-2xl font-bold text-slate-900 flex items-center">
                  <CheckCircle className="h-6 w-6 text-green-500 mr-2 print:hidden" />
                  Your Personalised Matches
                </h3>
                <p className="text-slate-600 mt-1">
                  Based on your profile, you are eligible for <strong className="text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">{results.length}</strong> government schemes.
                </p>
              </div>
              <div className="flex space-x-3 print:hidden">
                <button onClick={printResults} className="flex items-center px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 font-medium text-sm transition-colors shadow-sm">
                  <Printer className="h-4 w-4 mr-2" /> Print
                </button>
                <button onClick={resetForm} className="px-4 py-2 bg-slate-800 text-white rounded-lg hover:bg-slate-900 font-medium text-sm transition-colors shadow-sm">
                  Start Over
                </button>
              </div>
            </div>

            {/* User Profile Summary (Visible mainly for print) */}
            <div className="hidden print:block mb-8 p-4 border-2 border-slate-200 rounded-lg">
              <h4 className="font-bold text-lg mb-2">Profile Summary</h4>
              <p className="text-sm text-slate-600">Age: {formData.age} | Gender: {formData.gender} | Location: {formData.location}, {formData.state} | Occupation: {formData.occupation} | Income: ₹{formData.income}</p>
            </div>

            {results.length > 0 ? (
              <div className="space-y-6">
                {results.map((scheme) => (
                  <div key={scheme.id} className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group">
                    <div className="absolute top-0 left-0 w-1 h-full bg-indigo-500"></div>
                    
                    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 gap-2">
                      <h4 className="text-xl font-bold text-slate-800">{scheme.name}</h4>
                      <div className="flex flex-wrap gap-2">
                        {scheme.tags.map(tag => (
                          <span key={tag} className="px-2.5 py-1 bg-slate-100 text-slate-600 text-xs font-semibold rounded-md border border-slate-200">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                    
                    <p className="text-slate-600 mb-6">{scheme.description}</p>
                    
                    <div className="bg-indigo-50/50 p-4 rounded-lg border border-indigo-100/50">
                      <h5 className="text-sm font-bold text-slate-800 mb-3 flex items-center">
                        <FileText className="h-4 w-4 mr-1.5 text-indigo-500" /> Documents Needed for Application
                      </h5>
                      <ul className="grid sm:grid-cols-2 gap-y-2 gap-x-4">
                        {scheme.documents.map(doc => (
                          <li key={doc} className="text-sm text-slate-600 flex items-center">
                            <div className="h-1.5 w-1.5 bg-indigo-400 rounded-full mr-2"></div> {doc}
                          </li>
                        ))}
                      </ul>
                    </div>
                    
                    <div className="mt-6 flex justify-end print:hidden">
                      <button className="bg-emerald-600 text-white px-6 py-2 rounded-lg font-medium hover:bg-emerald-700 transition-colors shadow flex items-center group-hover:shadow-md">
                        Apply on Portal <ArrowRight className="ml-2 h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-16 bg-white rounded-xl border border-slate-200">
                <AlertCircle className="h-16 w-16 text-amber-500 mx-auto mb-4 opacity-80" />
                <h4 className="text-2xl font-bold text-slate-800 mb-2">No Direct Matches Found</h4>
                <p className="text-slate-600 max-w-md mx-auto mb-8">
                  Based on the specific inputs provided, we couldn't find an exact match in our top simulated schemes. You may still be eligible for state-specific micro-schemes not listed in this demo.
                </p>
                <button onClick={() => setStep(1)} className="bg-indigo-50 text-indigo-700 px-6 py-2.5 rounded-lg font-medium hover:bg-indigo-100 transition-colors border border-indigo-200">
                  Go Back & Adjust Details
                </button>
              </div>
            )}
            
            {/* Disclaimer */}
            <div className="mt-8 text-center text-xs text-slate-400 print:mt-12">
              <p>Disclaimer: This is an AI-powered simulation. Final eligibility is determined by the respective government authorities upon document verification.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}