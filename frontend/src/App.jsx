import { useState } from "react";

import {
  Activity,
  Bot,
  CalendarDays,
  CheckCircle2,
  Clock,
  Plus,
  Send,
  UserRound,
} from "lucide-react";

import { sendMessage } from "./services/api";

import "./App.css";


function createThreadId() {
  return crypto.randomUUID();
}


const INITIAL_MESSAGE = {
  role: "assistant",
  content:
    "Hello! I can help you find a doctor and schedule an appointment. What would you like to do?",
};


function App() {
  const [threadId, setThreadId] = useState(
    () => createThreadId()
  );

  const [messages, setMessages] = useState([
    INITIAL_MESSAGE,
  ]);

  const [input, setInput] = useState("");

  const [loading, setLoading] = useState(false);

  const [status, setStatus] = useState("ready");

  const [appointment, setAppointment] = useState({
    doctor: "",
    specialty: "",
    date: "",
    time: "",
    patient: "",
  });


  // ==========================================================
  // Start New Conversation
  // ==========================================================

  const startNewConversation = () => {
    setThreadId(
      createThreadId()
    );

    setMessages([
      INITIAL_MESSAGE,
    ]);

    setInput("");

    setLoading(false);

    setStatus("ready");

    setAppointment({
      doctor: "",
      specialty: "",
      date: "",
      time: "",
      patient: "",
    });
  };


  // ==========================================================
  // Send Message
  // ==========================================================

  const handleSubmit = async (
    event
  ) => {
    event.preventDefault();

    const query = input.trim();

    if (!query || loading) {
      return;
    }

    // Add user message immediately.
    setMessages(
      (previous) => [
        ...previous,
        {
          role: "user",
          content: query,
        },
      ]
    );

    setInput("");

    setLoading(true);

    try {
      const result =
        await sendMessage(
          query,
          threadId
        );

      // Add assistant response.
      setMessages(
        (previous) => [
          ...previous,
          {
            role: "assistant",
            content:
              result.response ||
              "I couldn't generate a response.",
          },
        ]
      );

      setStatus(
        result.status ||
        "completed"
      );

      /*
       * We still use the backend trace internally
       * to update the appointment summary.
       *
       * The trace itself is NOT displayed to users.
       */
      updateAppointmentFromTrace(
        result.trace || []
      );

    } catch (error) {
      console.error(
        "Scheduling error:",
        error
      );

      setMessages(
        (previous) => [
          ...previous,
          {
            role: "assistant",
            content:
              "Sorry, I couldn't connect to the scheduling service. Please make sure the scheduling service is running.",
          },
        ]
      );

      setStatus("error");

    } finally {
      setLoading(false);
    }
  };


  // ==========================================================
  // Update Appointment Summary
  // ==========================================================

  const updateAppointmentFromTrace = (
    items
  ) => {
    if (
      !Array.isArray(items) ||
      items.length === 0
    ) {
      return;
    }

    /*
     * Look for the latest request-analysis
     * result from LangGraph.
     */
    const analyzeNodes =
      items.filter(
        (item) =>
          item &&
          item.node ===
            "analyze_request"
      );

    if (
      analyzeNodes.length === 0
    ) {
      return;
    }

    const latest =
      analyzeNodes[
        analyzeNodes.length - 1
      ];

    const parsed =
      parseTraceDetails(
        latest.details
      );

    if (!parsed) {
      return;
    }


    /*
     * A doctor search or availability-date
     * lookup should not accidentally display
     * stale booking information.
     */
    if (
      parsed.intent ===
        "doctor_search" ||
      parsed.intent ===
        "availability_dates"
    ) {
      setAppointment(
        (previous) => ({
          doctor:
            parsed.doctor_name ||
            "",
          specialty:
            parsed.specialty ||
            "",
          date: "",
          time: "",
          patient: "",
        })
      );

      return;
    }


    /*
     * For appointment booking, preserve
     * previously collected information when
     * the current message doesn't contain it.
     */
    if (
      parsed.intent ===
      "appointment_booking"
    ) {
      setAppointment(
        (previous) => ({
          doctor:
            parsed.doctor_name ||
            previous.doctor,

          specialty:
            parsed.specialty ||
            previous.specialty,

          date:
            parsed.appointment_date ||
            previous.date,

          time:
            parsed.appointment_time ||
            previous.time,

          patient:
            parsed.patient_name ||
            previous.patient,
        })
      );
    }
  };


  return (
    <div className="app">

      {/* ================================================== */}
      {/* Header */}
      {/* ================================================== */}

      <header className="header">

        <div className="brand">

          <div className="brand-icon">
            <Activity size={22} />
          </div>

          <div>

            <h1>
              CareFlow AI
            </h1>

            <p>
              Agentic Healthcare Scheduling
            </p>

          </div>

        </div>


        <div className="header-actions">

          <div className="status-indicator">

            <span />

            Agent Online

          </div>


          <button
            type="button"
            className="new-chat-button"
            onClick={
              startNewConversation
            }
          >

            <Plus size={16} />

            New Conversation

          </button>

        </div>

      </header>


      {/* ================================================== */}
      {/* Main Dashboard */}
      {/* ================================================== */}

      <main className="dashboard">


        {/* ================================================= */}
        {/* Chat */}
        {/* ================================================= */}

        <section className="chat-section">

          <div className="section-header">

            <div>

              <h2>
                Scheduling Assistant
              </h2>

              <p>
                Talk naturally with the AI
                scheduling agent.
              </p>

            </div>

            <Bot size={24} />

          </div>


          <div className="messages">

            {messages.map(
              (message, index) => (

                <div
                  key={index}
                  className={
                    `message ${message.role}`
                  }
                >

                  <div className="message-icon">

                    {message.role ===
                    "assistant" ? (
                      <Bot size={17} />
                    ) : (
                      <UserRound
                        size={17}
                      />
                    )}

                  </div>


                  <div className="message-content">

                    {message.content}

                  </div>

                </div>

              )
            )}


            {loading && (

              <div className="message assistant">

                <div className="message-icon">

                  <Bot size={17} />

                </div>


                <div className="message-content loading-message">

                  <span className="loading-dot" />
                  <span className="loading-dot" />
                  <span className="loading-dot" />

                  <span className="loading-text">
                    Processing...
                  </span>

                </div>

              </div>

            )}

          </div>


          {/* ================================================= */}
          {/* Message Input */}
          {/* ================================================= */}

          <form
            className="input-area"
            onSubmit={
              handleSubmit
            }
          >

            <input
              type="text"
              value={input}
              onChange={
                (event) =>
                  setInput(
                    event.target.value
                  )
              }
              placeholder={
                "e.g. I need to see a dermatologist..."
              }
              disabled={loading}
              autoComplete="off"
            />


            <button
              type="submit"
              disabled={
                loading ||
                !input.trim()
              }
              aria-label="Send message"
            >

              <Send size={18} />

            </button>

          </form>

        </section>


        {/* ================================================= */}
        {/* Appointment Sidebar */}
        {/* ================================================= */}

        <aside className="sidebar">

          <AppointmentCard
            appointment={
              appointment
            }
            status={status}
          />

        </aside>

      </main>

    </div>
  );
}


// ============================================================
// Appointment Card
// ============================================================

function AppointmentCard({
  appointment,
  status,
}) {
  const confirmed =
    status ===
      "confirmed" ||
    status ===
      "booking_completed";


  const hasInformation =
    Boolean(
      appointment.doctor ||
      appointment.specialty ||
      appointment.date ||
      appointment.time ||
      appointment.patient
    );


  return (
    <div
      className={
        `card appointment-card ${
          confirmed
            ? "appointment-confirmed"
            : ""
        }`
      }
    >

      <div className="card-title">

        <div className="card-title-icon">

          <CalendarDays size={18} />

        </div>

        <div>

          <h3>
            Appointment
          </h3>

          <p>
            {confirmed
              ? "Your appointment details"
              : "Booking details"}
          </p>

        </div>

      </div>


      {!hasInformation && (

        <div className="appointment-empty">

          <CalendarDays size={28} />

          <p>
            Your doctor, date, time,
            and patient details will
            appear here as you continue.
          </p>

        </div>

      )}


      {hasInformation && (

        <div className="appointment-info">

          <InfoRow
            icon={
              <UserRound
                size={17}
              />
            }
            label="Doctor"
            value={
              appointment.doctor ||
              "Not selected"
            }
          />


          {appointment.specialty && (

            <InfoRow
              icon={
                <Activity
                  size={17}
                />
              }
              label="Specialty"
              value={
                appointment.specialty
              }
            />

          )}


          <InfoRow
            icon={
              <CalendarDays
                size={17}
              />
            }
            label="Date"
            value={
              appointment.date ||
              "Not selected"
            }
          />


          <InfoRow
            icon={
              <Clock
                size={17}
              />
            }
            label="Time"
            value={
              appointment.time ||
              "Not selected"
            }
          />


          <InfoRow
            icon={
              <UserRound
                size={17}
              />
            }
            label="Patient"
            value={
              appointment.patient ||
              "Not selected"
            }
          />

        </div>

      )}


      {confirmed && (

        <div className="confirmed">

          <CheckCircle2
            size={17}
          />

          Appointment Confirmed

        </div>

      )}

    </div>
  );
}


// ============================================================
// Information Row
// ============================================================

function InfoRow({
  icon,
  label,
  value,
}) {
  return (
    <div className="info-row">

      <div className="info-icon">

        {icon}

      </div>


      <div className="info-content">

        <span>
          {label}
        </span>

        <strong>
          {value}
        </strong>

      </div>

    </div>
  );
}


// ============================================================
// Trace Parser
// ============================================================

function parseTraceDetails(
  details
) {
  if (!details) {
    return null;
  }


  if (
    typeof details ===
    "object"
  ) {
    return details;
  }


  if (
    typeof details !==
    "string"
  ) {
    return null;
  }


  /*
   * First try normal JSON.
   */
  try {
    return JSON.parse(
      details
    );
  } catch {
    // Continue to Python-dict parsing.
  }


  /*
   * Your current backend may return
   * dictionary-like strings such as:
   *
   * {'intent': 'appointment_booking',
   *  'doctor_name': 'Emily Johnson'}
   *
   * Convert this limited trace format
   * safely without using eval().
   */
  try {
    const normalized =
      details
        .replace(
          /'/g,
          '"'
        )
        .replace(
          /\bNone\b/g,
          "null"
        )
        .replace(
          /\bTrue\b/g,
          "true"
        )
        .replace(
          /\bFalse\b/g,
          "false"
        );

    return JSON.parse(
      normalized
    );

  } catch {
    return null;
  }
}


export default App;