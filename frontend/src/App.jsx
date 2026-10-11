import { useEffect, useState } from "react";

import {
  Activity,
  Bot,
  CalendarDays,
  CheckCircle2,
  Clock,
  Database,
  FileJson,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Stethoscope,
  Upload,
  UserRound,
  Users,
} from "lucide-react";

import { sendMessage } from "./services/api";
import "./App.css";

const API_BASE_URL =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

function createThreadId() {
  return crypto.randomUUID();
}

const INITIAL_MESSAGE = {
  role: "assistant",
  content:
    "Hello! I can help you find a doctor and schedule an appointment. What would you like to do?",
};

const EMPTY_APPOINTMENT = {
  doctor: "",
  specialty: "",
  date: "",
  time: "",
  patient: "",
};

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);

  let data = {};
  try {
    data = await response.json();
  } catch {
    // Some errors may not return JSON.
  }

  if (!response.ok) {
    const detail = data.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ||
          (Array.isArray(detail?.errors) ? detail.errors.join("\n") : "") ||
          `Request failed with status ${response.status}.`;
    throw new Error(message);
  }

  return data;
}

function toFileFormData(file) {
  const formData = new FormData();
  formData.append("file", file);
  return formData;
}

function App() {
  const [activeView, setActiveView] = useState("chat");

  // Existing scheduling assistant state and behavior.
  const [threadId, setThreadId] = useState(() => createThreadId());
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("ready");
  const [appointment, setAppointment] = useState(EMPTY_APPOINTMENT);

  // Doctor administration state.
  const [doctorFile, setDoctorFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [importResult, setImportResult] = useState(null);
  const [adminLoading, setAdminLoading] = useState(false);
  const [adminError, setAdminError] = useState("");
  const [summary, setSummary] = useState(null);
  const [doctors, setDoctors] = useState([]);
  const [directoryLoading, setDirectoryLoading] = useState(false);
  const [directoryError, setDirectoryError] = useState("");

  // ==========================================================
  // Start New Conversation (existing functionality)
  // ==========================================================
  const startNewConversation = () => {
    setThreadId(createThreadId());
    setMessages([INITIAL_MESSAGE]);
    setInput("");
    setLoading(false);
    setStatus("ready");
    setAppointment(EMPTY_APPOINTMENT);
  };

  // ==========================================================
  // Send Message (existing functionality)
  // ==========================================================
  const handleSubmit = async (event) => {
    event.preventDefault();

    const query = input.trim();
    if (!query || loading) return;

    setMessages((previous) => [
      ...previous,
      { role: "user", content: query },
    ]);
    setInput("");
    setLoading(true);

    try {
      const result = await sendMessage(query, threadId);

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: result.response || "I couldn't generate a response.",
        },
      ]);

      setStatus(result.status || "completed");
      updateAppointmentFromTrace(result.trace || []);
    } catch (error) {
      console.error("Scheduling error:", error);

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content:
            "Sorry, I couldn't connect to the scheduling service. Please make sure the scheduling service is running.",
        },
      ]);
      setStatus("error");
    } finally {
      setLoading(false);
    }
  };

  // ==========================================================
  // Existing appointment-summary parsing
  // ==========================================================
  const updateAppointmentFromTrace = (items) => {
    if (!Array.isArray(items) || items.length === 0) return;

    const analyzeNodes = items.filter(
      (item) => item && item.node === "analyze_request"
    );
    if (analyzeNodes.length === 0) return;

    const latest = analyzeNodes[analyzeNodes.length - 1];
    const parsed = parseTraceDetails(latest.details);
    if (!parsed) return;

    if (
      parsed.intent === "doctor_search" ||
      parsed.intent === "availability_dates"
    ) {
      setAppointment({
        doctor: parsed.doctor_name || "",
        specialty: parsed.specialty || "",
        date: "",
        time: "",
        patient: "",
      });
      return;
    }

    if (parsed.intent === "appointment_booking") {
      setAppointment((previous) => ({
        doctor: parsed.doctor_name || previous.doctor,
        specialty: parsed.specialty || previous.specialty,
        date: parsed.appointment_date || previous.date,
        time: parsed.appointment_time || previous.time,
        patient: parsed.patient_name || previous.patient,
      }));
    }
  };

  // ==========================================================
  // Doctor directory
  // ==========================================================
  const loadDoctorDirectory = async () => {
    setDirectoryLoading(true);
    setDirectoryError("");

    try {
      const [summaryData, directoryData] = await Promise.all([
        requestJson("/api/v1/admin/doctors/summary"),
        requestJson("/api/v1/admin/doctors"),
      ]);

      setSummary(summaryData);
      setDoctors(Array.isArray(directoryData.doctors) ? directoryData.doctors : []);
    } catch (error) {
      console.error("Doctor directory request failed:", error);
      setDirectoryError(error.message);
    } finally {
      setDirectoryLoading(false);
    }
  };

  useEffect(() => {
    if (activeView === "admin") {
      loadDoctorDirectory();
    }
  }, [activeView]);

  // ==========================================================
  // Upload and validate doctors.json
  // ==========================================================
  const handleFileChange = (event) => {
    const file = event.target.files?.[0] || null;

    setDoctorFile(file);
    setPreview(null);
    setImportResult(null);
    setAdminError("");

    if (file && !file.name.toLowerCase().endsWith(".json")) {
      setAdminError("Please choose a .json file.");
    } else if (file && file.size > 2 * 1024 * 1024) {
      setAdminError("The selected file exceeds the 2 MB limit.");
    }
  };

  const handlePreview = async () => {
    if (!doctorFile) {
      setAdminError("Choose a JSON file first.");
      return;
    }
    if (!doctorFile.name.toLowerCase().endsWith(".json")) {
      setAdminError("Please choose a .json file.");
      return;
    }
    if (doctorFile.size > 2 * 1024 * 1024) {
      setAdminError("The selected file exceeds the 2 MB limit.");
      return;
    }

    setAdminLoading(true);
    setAdminError("");
    setPreview(null);
    setImportResult(null);

    try {
      const result = await requestJson(
        "/api/v1/admin/doctors/preview",
        {
          method: "POST",
          body: toFileFormData(doctorFile),
        }
      );

      setPreview(result);
      if (!result.valid) {
        setAdminError(
          (result.errors || []).join("\n") ||
            "The file did not pass validation."
        );
      }
    } catch (error) {
      setAdminError(error.message);
    } finally {
      setAdminLoading(false);
    }
  };

  // ==========================================================
  // Explicit database initialization/import
  // ==========================================================
  const handleInitialize = async () => {
    if (!doctorFile || !preview?.valid) {
      setAdminError("Choose a file and complete a successful preview first.");
      return;
    }

    const confirmed = window.confirm(
      "Import these doctor records? Existing matching doctors may be updated. Records omitted from the file will not be deleted."
    );
    if (!confirmed) return;

    setAdminLoading(true);
    setAdminError("");
    setImportResult(null);

    try {
      const result = await requestJson(
        "/api/v1/admin/doctors/initialize",
        {
          method: "POST",
          body: toFileFormData(doctorFile),
        }
      );

      setImportResult(result);
      setPreview(null);
      setDoctorFile(null);

      const fileInput = document.getElementById("doctor-json-file");
      if (fileInput) fileInput.value = "";

      await loadDoctorDirectory();
    } catch (error) {
      setAdminError(error.message);
    } finally {
      setAdminLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand-icon">
            <Activity size={22} />
          </div>
          <div>
            <h1>CareFlow AI</h1>
            <p>Agentic Healthcare Scheduling</p>
          </div>
        </div>

        <div className="header-actions">
          <div className="status-indicator">
            <span />
            Agent Online
          </div>
          {activeView === "chat" && (
            <button
              type="button"
              className="new-chat-button"
              onClick={startNewConversation}
            >
              <Plus size={16} />
              New Conversation
            </button>
          )}
        </div>
      </header>

      <nav className="view-tabs" aria-label="Application views">
        <button
          type="button"
          className={`view-tab ${activeView === "chat" ? "active" : ""}`}
          onClick={() => setActiveView("chat")}
        >
          <Bot size={17} />
          Scheduling Assistant
        </button>
        <button
          type="button"
          className={`view-tab ${activeView === "admin" ? "active" : ""}`}
          onClick={() => setActiveView("admin")}
        >
          <Database size={17} />
          Doctor Management
        </button>
      </nav>

      {activeView === "chat" ? (
        <main className="dashboard">
          <section className="chat-section">
            <div className="section-header">
              <div>
                <h2>Scheduling Assistant</h2>
                <p>
                  Talk naturally with the AI scheduling agent.
                </p>
              </div>
            </div>

            <div className="messages">
              {messages.map((message, index) => (
                <div
                  key={`${index}-${message.role}`}
                  className={`message ${message.role}`}
                >
                  <div className="message-icon">
                    {message.role === "assistant" ? (
                      <Bot size={17} />
                    ) : (
                      <UserRound size={17} />
                    )}
                  </div>
                  <div className="message-content">{message.content}</div>
                </div>
              ))}

              {loading && (
                <div className="message assistant">
                  <div className="message-icon">
                    <Bot size={17} />
                  </div>
                  <div className="message-content loading-message">
                    <span className="loading-dot" />
                    <span className="loading-dot" />
                    <span className="loading-dot" />
                    <span className="loading-text">Processing...</span>
                  </div>
                </div>
              )}
            </div>

            <form className="input-area" onSubmit={handleSubmit}>
              <input
                type="text"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="e.g. I need to see a dermatologist..."
                disabled={loading}
                autoComplete="off"
              />
              <button
                type="submit"
                disabled={loading || !input.trim()}
                aria-label="Send message"
              >
                <Send size={18} />
              </button>
            </form>
          </section>

          <aside className="sidebar">
            <AppointmentCard appointment={appointment} status={status} />
          </aside>
        </main>
      ) : (
        <main className="admin-page">
          <div className="admin-heading">
            <div>
              <p className="eyebrow">ADMINISTRATION</p>
              <h2>Doctor Management</h2>
              <p>
                Upload a JSON file, review its records, and explicitly import
                the validated doctors into the database.
              </p>
            </div>
            <button
              type="button"
              className="secondary-button"
              onClick={loadDoctorDirectory}
              disabled={directoryLoading}
            >
              <RefreshCw size={16} />
              Refresh directory
            </button>
          </div>

          <section className="summary-grid">
            <SummaryCard
              icon={<Users size={21} />}
              label="Total doctors"
              value={summary?.total_doctors ?? "—"}
            />
            <SummaryCard
              icon={<Stethoscope size={21} />}
              label="Specialties"
              value={summary?.total_specialties ?? "—"}
            />
            <SummaryCard
              icon={<ShieldCheck size={21} />}
              label="File validation"
              value={preview ? (preview.valid ? "Passed" : "Failed") : "Pending"}
            />
          </section>

          <section className="admin-card">
            <div className="admin-card-heading">
              <div className="admin-card-icon">
                <FileJson size={21} />
              </div>
              <div>
                <h3>Import doctors from JSON</h3>
                <p>JSON array · Maximum 2 MB · Preview before importing</p>
              </div>
            </div>

            <label className="file-drop" htmlFor="doctor-json-file">
              <Upload size={26} />
              <strong>
                {doctorFile ? doctorFile.name : "Choose your doctors.json file"}
              </strong>
              <span>
                {doctorFile
                  ? `${(doctorFile.size / 1024).toFixed(1)} KB`
                  : "Choose a JSON file from your computer"}
              </span>
              <input
                id="doctor-json-file"
                type="file"
                accept=".json,application/json"
                onChange={handleFileChange}
              />
            </label>

            <div className="admin-actions">
              <button
                type="button"
                className="primary-button"
                onClick={handlePreview}
                disabled={!doctorFile || adminLoading}
              >
                {adminLoading ? "Please wait..." : "Validate and preview"}
              </button>
              <button
                type="button"
                className="initialize-button"
                onClick={handleInitialize}
                disabled={!doctorFile || !preview?.valid || adminLoading}
              >
                <Database size={17} />
                Initialize database
              </button>
            </div>

            <p className="helper-text">
              Preview does not change the database. Import can insert new
              doctors and update existing matching records. Omitted doctors
              are not automatically deleted.
            </p>

            {adminError && (
              <div className="feedback error-feedback" role="alert">
                <strong>Action required</strong>
                <pre>{adminError}</pre>
              </div>
            )}

            {preview?.valid && (
              <div className="feedback success-feedback" role="status">
                <CheckCircle2 size={19} />
                <div>
                  <strong>Validation successful</strong>
                  <p>{preview.count} doctor records are ready to import.</p>
                </div>
              </div>
            )}

            {importResult && (
              <div className="feedback success-feedback" role="status">
                <CheckCircle2 size={19} />
                <div>
                  <strong>Import completed</strong>
                  <p>{importResult.message}</p>
                  <p>
                    Inserted: {importResult.inserted} · Updated:{" "}
                    {importResult.updated} · Processed:{" "}
                    {importResult.total_processed}
                  </p>
                </div>
              </div>
            )}

            {preview?.doctors?.length > 0 && (
              <div className="preview-table-wrap">
                <h4>Preview records</h4>
                <DoctorTable doctors={preview.doctors} />
              </div>
            )}
          </section>

          <section className="admin-card">
            <div className="admin-card-heading">
              <div className="admin-card-icon">
                <Stethoscope size={21} />
              </div>
              <div>
                <h3>Doctor directory</h3>
                <p>Records currently stored in the database</p>
              </div>
            </div>

            {directoryLoading ? (
              <p className="empty-directory">Loading doctor directory...</p>
            ) : directoryError ? (
              <div className="feedback error-feedback" role="alert">
                <strong>Could not load the directory</strong>
                <pre>{directoryError}</pre>
              </div>
            ) : doctors.length ? (
              <DoctorTable doctors={doctors} />
            ) : (
              <div className="empty-directory">
                <Stethoscope size={28} />
                <strong>No doctors found</strong>
                <p>Import a validated JSON file to populate the directory.</p>
              </div>
            )}
          </section>
        </main>
      )}
    </div>
  );
}

function SummaryCard({ icon, label, value }) {
  return (
    <div className="summary-card">
      <div className="summary-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function DoctorTable({ doctors }) {
  return (
    <div className="doctor-table-wrap">
      <table className="doctor-table">
        <thead>
          <tr>
            <th>Doctor</th>
            <th>Specialty</th>
            <th>Experience</th>
            <th>Description</th>
          </tr>
        </thead>
        <tbody>
          {doctors.map((doctor, index) => (
            <tr key={`${doctor.name}-${index}`}>
              <td>
                <div className="doctor-name-cell">
                  <div className="doctor-avatar">
                    <UserRound size={17} />
                  </div>
                  <strong>{doctor.name}</strong>
                </div>
              </td>
              <td>
                <span className="specialty-pill">{doctor.specialty}</span>
              </td>
              <td>{doctor.experience} years</td>
              <td>{doctor.description || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Existing appointment card, with the specialty field preserved.
function AppointmentCard({ appointment, status }) {
  const confirmed =
    status === "confirmed" || status === "booking_completed";

  const hasInformation = Boolean(
    appointment.doctor ||
      appointment.specialty ||
      appointment.date ||
      appointment.time ||
      appointment.patient
  );

  return (
    <div
      className={`card appointment-card ${
        confirmed ? "appointment-confirmed" : ""
      }`}
    >
      <div className="card-title">
        <div className="card-title-icon">
          <CalendarDays size={18} />
        </div>
        <div>
          <h3>Appointment</h3>
          <p>{confirmed ? "Your appointment details" : "Booking details"}</p>
        </div>
      </div>

      {!hasInformation && (
        <div className="appointment-empty">
          <CalendarDays size={28} />
          <p>
            Your doctor, date, time, and patient details will appear here as
            you continue.
          </p>
        </div>
      )}

      {hasInformation && (
        <div className="appointment-info">
          <InfoRow
            icon={<UserRound size={17} />}
            label="Doctor"
            value={appointment.doctor || "Not selected"}
          />

          {appointment.specialty && (
            <InfoRow
              icon={<Activity size={17} />}
              label="Specialty"
              value={appointment.specialty}
            />
          )}

          <InfoRow
            icon={<CalendarDays size={17} />}
            label="Date"
            value={appointment.date || "Not selected"}
          />
          <InfoRow
            icon={<Clock size={17} />}
            label="Time"
            value={appointment.time || "Not selected"}
          />
          <InfoRow
            icon={<UserRound size={17} />}
            label="Patient"
            value={appointment.patient || "Not selected"}
          />
        </div>
      )}

      {confirmed && (
        <div className="confirmed">
          <CheckCircle2 size={17} />
          Appointment Confirmed
        </div>
      )}
    </div>
  );
}

function InfoRow({ icon, label, value }) {
  return (
    <div className="info-row">
      <div className="info-icon">{icon}</div>
      <div className="info-content">
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

// Keep the trace parser from the attached App.jsx.
// The trace is used internally for appointment summary and is not displayed.
function parseTraceDetails(details) {
  if (!details) return null;
  if (typeof details === "object") return details;
  if (typeof details !== "string") return null;

  try {
    return JSON.parse(details);
  } catch {
    // Continue to the limited Python-dict fallback below.
  }

  try {
    const normalized = details
      .replace(/'/g, '"')
      .replace(/\bNone\b/g, "null")
      .replace(/\bTrue\b/g, "true")
      .replace(/\bFalse\b/g, "false");

    return JSON.parse(normalized);
  } catch {
    return null;
  }
}

export default App;
